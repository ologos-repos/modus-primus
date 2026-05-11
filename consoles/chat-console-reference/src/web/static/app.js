// chat console — main client. Vanilla JS, no framework.
// Wiring: theme + new-session + composer → POST /turns → SSE consume → DOM updates.
// Resilience: visibilitychange resumes the stream from the last-seen offset.

(() => {
    "use strict";

    // PWA / standalone detection — iOS Safari sets navigator.standalone, others
    // expose it via the matchMedia display-mode query. We tag the root element
    // so CSS can target .pwa-standalone reliably (the @media query alone has
    // proven flaky on installed iOS PWAs).
    if (
        window.navigator.standalone === true ||
        (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches)
    ) {
        document.documentElement.classList.add("pwa-standalone");
    }

    const LS_THEME = "console.theme";
    const LS_SESSION = "console.session_id";

    // ---- DOM refs ----
    const conv = document.getElementById("conversation");
    const form = document.getElementById("composer-form");
    const input = document.getElementById("prompt-input");
    const sendBtn = document.getElementById("send-btn");
    const themeBtn = document.getElementById("theme-toggle");
    const sidebarBtn = document.getElementById("sidebar-toggle");
    const sidebar = document.getElementById("sidebar");
    const newSessionBtn = document.getElementById("new-session-btn");
    const meter = document.getElementById("meter");
    const notifBtn = document.getElementById("notif-btn");
    const attachBtn = document.getElementById("attach-btn");
    const attachInput = document.getElementById("attach-input");
    const attachmentsEl = document.getElementById("attachments");

    // ---- state ----
    const state = {
        theme: localStorage.getItem(LS_THEME) || "dark",
        sessionId: localStorage.getItem(LS_SESSION),
        turnId: null,
        eventOffset: 0,
        currentBlock: null,            // .block (entire turn container)
        currentTurnEventsEl: null,     // .turn-events (where dynamic events flow)
        currentTextBlock: null,        // .text-block | null — open token-run, if any
        currentTextRunBuffer: "",      // accumulated text for the open text-run
        lastEventType: null,           // for token-run partitioning
        statusFooterEl: null,          // .turn-status-footer | null
        turnStartedAt: 0,              // ms since epoch (for elapsed display)
        statusTickerId: null,          // setInterval handle for the 1s footer tick
        activityLabel: "Propagating…", // current activity hint
        currentTurnOutputTokens: 0,    // cumulative output_tokens for THIS turn
        latestUsage: null,
        wakeLock: null,
        swRegistration: null,
        pendingAttachments: [],  // {id, file (Blob), name, size}
        lastEventAt: 0,          // ms timestamp of the last received SSE event
        turnInFlight: false,     // true between submitTurn start and onTurnComplete
        queuedPrompt: null,      // prompt typed during in-flight; awaits disposition (#32)
        queuedAttachments: [],
        pendingAgentRuns: {},    // run_id → {block, agentName, startedAt, pollDelayMs} (#33)
    };

    // ===== theme =====
    function applyTheme() {
        document.documentElement.setAttribute("data-theme", state.theme);
    }
    themeBtn.addEventListener("click", () => {
        state.theme = state.theme === "dark" ? "light" : "dark";
        localStorage.setItem(LS_THEME, state.theme);
        applyTheme();
    });
    applyTheme();

    // ===== sidebar toggle (mobile overlay + desktop collapse) =====
    const LS_SIDEBAR_COLLAPSED = "console.sidebar.collapsed";
    const layoutEl = document.querySelector(".layout");
    // Apply persisted desktop-collapse state on boot.
    if (localStorage.getItem(LS_SIDEBAR_COLLAPSED) === "1") {
        layoutEl.classList.add("sidebar-collapsed");
    }
    sidebarBtn.addEventListener("click", () => {
        const isMobile = window.matchMedia("(max-width: 768px)").matches;
        if (isMobile) {
            sidebar.classList.toggle("open");
        } else {
            const collapsed = layoutEl.classList.toggle("sidebar-collapsed");
            localStorage.setItem(LS_SIDEBAR_COLLAPSED, collapsed ? "1" : "0");
        }
    });

    // ===== new session =====
    newSessionBtn.addEventListener("click", () => {
        if (!confirm("Start a new conversation? Current Claude memory persists; UI inserts a separator.")) return;
        wrapSession();
    });

    function wrapSession() {
        state.sessionId = null;
        localStorage.removeItem(LS_SESSION);
        state.latestUsage = null;
        renderMeter();
        const sep = document.createElement("div");
        sep.className = "notice session-break";
        sep.textContent = "— new session —";
        conv.appendChild(sep);
        conv.scrollTop = conv.scrollHeight;
    }

    // ===== composer =====
    function autosizeInput() {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 200) + "px";
    }
    input.addEventListener("input", autosizeInput);
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey) {
            e.preventDefault();
            form.requestSubmit();
        }
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const prompt = input.value.trim();
        const hasAttachments = state.pendingAttachments.length > 0;
        if (!prompt && !hasAttachments) return;
        // Slash command — `/agent <name> <prompt>` dispatches directly to
        // the agents service, bypassing claude. Per chat-console#33.
        const slash = prompt.match(/^\/agent\s+(\S+)\s+([\s\S]+)$/);
        if (slash) {
            input.value = "";
            autosizeInput();
            spawnAgentRun(slash[1], slash[2]);
            return;
        }
        // If a turn is already in-flight, queue this prompt for disposition
        // when the current turn completes (per chat-console#32).
        if (state.turnInFlight) {
            state.queuedPrompt = prompt;
            state.queuedAttachments = state.pendingAttachments.slice();
            state.pendingAttachments = [];
            renderAttachments();
            input.value = "";
            autosizeInput();
            renderQueueIndicator();
            return;
        }
        input.value = "";
        autosizeInput();
        await submitTurn(prompt);
    });

    // ===== attachments =====
    attachBtn.addEventListener("click", () => attachInput.click());
    attachInput.addEventListener("change", () => {
        for (const file of attachInput.files) {
            enqueueAttachment(file);
        }
        attachInput.value = "";  // allow re-picking same file
    });

    input.addEventListener("paste", (e) => {
        if (!e.clipboardData) return;
        // Files in clipboardData (image paste, file paste from Finder)
        const files = Array.from(e.clipboardData.files || []);
        if (files.length > 0) {
            e.preventDefault();
            for (const file of files) enqueueAttachment(file);
            return;
        }
        // Items API for older browsers — pull image-type items
        for (const item of e.clipboardData.items || []) {
            if (item.kind === "file") {
                const f = item.getAsFile();
                if (f) {
                    e.preventDefault();
                    enqueueAttachment(f);
                }
            }
        }
        // text paste falls through to native textarea behavior
    });

    function enqueueAttachment(file) {
        const id = crypto.randomUUID
            ? crypto.randomUUID()
            : String(Math.random()).slice(2);
        // Paste-image files often have generic names like "image.png" — that's fine.
        state.pendingAttachments.push({
            id,
            file,
            name: file.name || "pasted-image.png",
            size: file.size || 0,
        });
        renderAttachments();
    }

    function removeAttachment(id) {
        state.pendingAttachments = state.pendingAttachments.filter((a) => a.id !== id);
        renderAttachments();
    }

    function renderAttachments() {
        if (state.pendingAttachments.length === 0) {
            attachmentsEl.hidden = true;
            attachmentsEl.innerHTML = "";
            return;
        }
        attachmentsEl.hidden = false;
        attachmentsEl.innerHTML = "";
        for (const a of state.pendingAttachments) {
            const chip = document.createElement("div");
            chip.className = "attachment-chip";

            const name = document.createElement("span");
            name.className = "name";
            name.textContent = a.name;
            chip.appendChild(name);

            const size = document.createElement("span");
            size.className = "size";
            size.textContent = formatSize(a.size);
            chip.appendChild(size);

            const remove = document.createElement("button");
            remove.className = "remove";
            remove.type = "button";
            remove.setAttribute("aria-label", "Remove attachment");
            remove.textContent = "×";
            remove.addEventListener("click", () => removeAttachment(a.id));
            chip.appendChild(remove);

            attachmentsEl.appendChild(chip);
        }
    }

    function formatSize(bytes) {
        if (bytes < 1024) return `${bytes}B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
    }

    async function uploadPendingAttachments() {
        const uploaded = [];
        for (const a of state.pendingAttachments) {
            const form = new FormData();
            form.append("file", a.file, a.name);
            try {
                const resp = await fetch("/uploads", { method: "POST", body: form });
                if (!resp.ok) {
                    console.warn("upload failed", a.name, resp.status);
                    continue;
                }
                const data = await resp.json();
                uploaded.push(data);
            } catch (e) {
                console.warn("upload error", a.name, e);
            }
        }
        return uploaded;
    }

    // ===== turn submission =====
    async function submitTurn(promptText) {
        state.turnInFlight = true;
        renderQueueIndicator();

        // Upload any pending attachments first; build the prompt prefix for paths.
        let attachmentPrefix = "";
        let uploadedFiles = [];
        if (state.pendingAttachments.length > 0) {
            uploadedFiles = await uploadPendingAttachments();
            if (uploadedFiles.length > 0) {
                const refs = uploadedFiles.map((u) => `@${u.path}`).join("\n");
                attachmentPrefix = `${refs}\n\n`;
            }
            state.pendingAttachments = [];
            renderAttachments();
        }

        const fullPrompt = attachmentPrefix + (promptText || "");
        // What we render as the user line — show filenames, not full paths,
        // so the conversation log stays readable.
        const displayPrompt = uploadedFiles.length
            ? `${uploadedFiles.map((u) => `[📎 ${u.name}]`).join(" ")}${promptText ? `\n${promptText}` : ""}`
            : promptText;

        // Render block immediately (before server roundtrip)
        const block = document.createElement("div");
        block.className = "block";

        const userP = document.createElement("div");
        userP.className = "user-prompt";
        userP.textContent = displayPrompt;
        block.appendChild(userP);

        // .turn-events is the flow container — token-runs, tool-blocks,
        // thinking-blocks, agent_completion notes all append into it in
        // arrival order so the visual sequence matches event order
        // (think → tool → think → answer, etc.) — per chat-console#25.
        const turnEvents = document.createElement("div");
        turnEvents.className = "turn-events";
        block.appendChild(turnEvents);

        // Live status footer — animated spinner + activity + elapsed/tokens.
        // Visible while RUNNING; replaced by completion summary on terminal.
        const footer = createStatusFooter();
        block.appendChild(footer);

        conv.appendChild(block);
        conv.scrollTop = conv.scrollHeight;

        state.currentBlock = block;
        state.currentTurnEventsEl = turnEvents;
        state.currentTextBlock = null;
        state.currentTextRunBuffer = "";
        state.lastEventType = null;
        state.statusFooterEl = footer;
        state.turnStartedAt = Date.now();
        state.activityLabel = "Propagating…";
        state.currentTurnOutputTokens = 0;
        state.eventOffset = 0;

        if (state.statusTickerId) clearInterval(state.statusTickerId);
        state.statusTickerId = setInterval(tickStatus, 1000);

        const body = { prompt: fullPrompt };
        if (state.sessionId) body.session_id = state.sessionId;

        let data;
        try {
            const resp = await fetch("/turns", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            if (!resp.ok) {
                const errText = await resp.text();
                renderInlineError(turnEvents, `submission failed (${resp.status}): ${errText}`);
                state.turnInFlight = false;
                renderQueueIndicator();
                return;
            }
            data = await resp.json();
        } catch (e) {
            renderInlineError(turnEvents, `network error: ${e.message}`);
            state.turnInFlight = false;
            renderQueueIndicator();
            return;
        }

        state.turnId = data.turn_id;
        state.sessionId = data.session_id;
        localStorage.setItem(LS_SESSION, data.session_id);

        // Synchronous (chat-console#28): the POST already returned the full event
        // log. Replay it through handleEvent so the existing render path
        // builds the DOM, then run completion cleanup.
        const events = data.events || [];
        for (const evt of events) {
            handleEvent(evt);
            state.eventOffset += 1;
        }
        if (typeof data.output_tokens_final === "number") {
            state.currentTurnOutputTokens = data.output_tokens_final;
        }
        onTurnComplete({ status: data.status, error: data.error });
    }

    function handleEvent(evt) {
        state.lastEventAt = Date.now();

        // Token-run partitioning: a contiguous run of `token` events forms
        // one .text-block paragraph. Any non-token event closes the run so
        // the next token starts a fresh paragraph. This is what fixes the
        // "exploded stream" — distinct streaming bursts (separated by tool
        // calls) render as separate paragraphs interleaved with tool-blocks
        // in arrival order, matching the visual hierarchy of terminal Claude.
        if (evt.type !== "token" && state.currentTextBlock) {
            state.currentTextBlock.classList.remove("streaming");
            enhanceDiagramBlocks(state.currentTextBlock);  // #36 — diagram render
            state.currentTextBlock = null;
            state.currentTextRunBuffer = "";
        }

        switch (evt.type) {
            case "token":
                appendTokenToTextRun(evt.data?.text || "");
                updateActivity("Streaming response…");
                break;
            case "tool_call":
                renderToolCall(evt.data || {});
                updateActivity(`Running tool · ${evt.data?.name || "?"}`);
                break;
            case "tool_result":
                renderToolResult(evt.data || {});
                updateActivity("Reading result…");
                break;
            case "thinking":
                renderThinking(evt.data || {});
                updateActivity("Thinking more…");
                break;
            case "usage":
                state.latestUsage = evt.data || null;
                if (typeof evt.data?.output_tokens === "number") {
                    state.currentTurnOutputTokens = evt.data.output_tokens;
                }
                renderMeter();
                break;
        }
        state.lastEventType = evt.type;
    }

    function appendTokenToTextRun(text) {
        if (!text) return;
        if (!state.currentTextBlock) {
            state.currentTextBlock = document.createElement("div");
            state.currentTextBlock.className = "text-block streaming";
            state.currentTurnEventsEl.appendChild(state.currentTextBlock);
            state.currentTextRunBuffer = "";
        }
        state.currentTextRunBuffer += text;
        state.currentTextBlock.innerHTML = renderMarkdown(state.currentTextRunBuffer);
        conv.scrollTop = conv.scrollHeight;
    }

    function onTurnComplete(payload) {
        // Close any open text-run.
        if (state.currentTextBlock) {
            state.currentTextBlock.classList.remove("streaming");
            enhanceDiagramBlocks(state.currentTextBlock);  // #36
            state.currentTextBlock = null;
            state.currentTextRunBuffer = "";
        }
        // Stop the status ticker; replace footer content with the completion
        // summary (no spinner, no live counters).
        if (state.statusTickerId) {
            clearInterval(state.statusTickerId);
            state.statusTickerId = null;
        }
        if (state.statusFooterEl) {
            const elapsed = Math.floor((Date.now() - state.turnStartedAt) / 1000);
            const tokens = state.currentTurnOutputTokens || 0;
            const tokensStr = formatTokenCount(tokens);
            state.statusFooterEl.classList.add("completed");
            state.statusFooterEl.innerHTML = "";
            const summary = document.createElement("span");
            summary.className = "status-completed";
            summary.textContent = `completed in ${elapsed}s · ↓${tokensStr} tokens`;
            state.statusFooterEl.appendChild(summary);
        }
        if (payload.error && state.currentTurnEventsEl) {
            renderInlineError(state.currentTurnEventsEl, `turn error: ${payload.error}`);
        }
        state.turnInFlight = false;
        releaseWakeLock();
        // Banner ping if user backgrounded the tab during the turn.
        const previewText = (state.currentTurnEventsEl?.textContent || "").trim().slice(0, 140);
        maybeNotify("chat-console — turn complete", previewText || "response ready");
        // Pull authoritative session stats + refresh sidebar list (last
        // activity / turn count update for the active session).
        refreshSessionStats();
        refreshSessions();
        // If a prompt was queued during the in-flight turn, transition the
        // queue indicator from "queued" to "ready" so JD picks the
        // disposition (send / edit / drop) — per chat-console#32.
        renderQueueIndicator();
        if (!state.queuedPrompt) input.focus();
    }

    // ===== render helpers =====
    // A tool_call creates a .tool-block with header only; the matching
    // tool_result fills in the indented body below it. Long tool output
    // collapses to first-N + last-M + "+K lines" indicator (click to expand).
    // Per chat-console#25.
    function renderToolCall(data) {
        const tb = document.createElement("div");
        tb.className = "tool-block";
        if (data.id) tb.dataset.toolUseId = data.id;

        const header = document.createElement("div");
        header.className = "tool-header";
        const marker = document.createElement("span");
        marker.className = "tool-marker";
        marker.textContent = "▸";
        const name = document.createElement("span");
        name.className = "tool-name";
        name.textContent = data.name || "tool";
        const open = document.createTextNode("(");
        const preview = document.createElement("span");
        preview.className = "tool-input-preview";
        preview.textContent = formatInputPreview(data.input);
        const close = document.createTextNode(")");
        header.append(marker, " ", name, open, preview, close);
        tb.appendChild(header);

        state.currentTurnEventsEl.appendChild(tb);
        conv.scrollTop = conv.scrollHeight;
    }

    function renderToolResult(data) {
        let content = data.content;
        if (Array.isArray(content)) {
            content = content
                .map((c) => (typeof c === "string" ? c : c?.text || JSON.stringify(c)))
                .join("\n");
        }
        const text = String(content ?? "");

        const body = document.createElement("div");
        body.className = "tool-body" + (data.is_error ? " error" : "");

        // Collapse threshold per #25: first 5 + last 3 + "+N lines" affordance.
        const lines = text.split("\n");
        const COLLAPSE_LINES = 12;
        const COLLAPSE_CHARS = 800;
        if (lines.length > COLLAPSE_LINES || text.length > COLLAPSE_CHARS) {
            const head = lines.slice(0, 5).join("\n");
            const tail = lines.slice(-3).join("\n");
            const remaining = lines.length - 8;
            const summary = document.createElement("div");
            summary.className = "tool-body-summary";
            summary.textContent =
                head + "\n  …\n" + tail +
                `\n  … +${remaining > 0 ? remaining : 0} lines (click to expand)`;
            const full = document.createElement("div");
            full.className = "tool-body-full";
            full.textContent = text;
            full.style.display = "none";
            body.appendChild(summary);
            body.appendChild(full);
            body.classList.add("collapsed", "collapsible");
            body.addEventListener("click", () => {
                const isCollapsed = body.classList.toggle("collapsed");
                summary.style.display = isCollapsed ? "" : "none";
                full.style.display = isCollapsed ? "none" : "";
            });
        } else {
            body.textContent = text;
        }

        const matching = data.tool_use_id
            ? state.currentTurnEventsEl.querySelector(
                  `.tool-block[data-tool-use-id="${CSS.escape(data.tool_use_id)}"]`
              )
            : null;
        if (matching) {
            matching.appendChild(body);
        } else {
            // Orphan result — shouldn't normally happen. Log so dev-tools
            // surfaces it; render in flow with a loud orphan style.
            console.warn("[chat] tool_result orphan", {
                wantId: data.tool_use_id,
                presentIds: Array.from(
                    state.currentTurnEventsEl.querySelectorAll(".tool-block")
                ).map((el) => el.dataset.toolUseId),
            });
            const tb = document.createElement("div");
            tb.className = "tool-block orphan";
            tb.appendChild(body);
            state.currentTurnEventsEl.appendChild(tb);
        }
        conv.scrollTop = conv.scrollHeight;
    }

    function renderThinking(data) {
        // Extended-thinking reasoning. Visible + dim, appended into the
        // turn-events container in arrival order so it interleaves
        // naturally with text-blocks and tool-blocks (think → tool → think
        // → answer). Per chat-console#21 + chat-console#25.
        const card = document.createElement("div");
        card.className = "thinking-block";

        const header = document.createElement("div");
        header.className = "thinking-header";
        header.textContent = "▸ thinking";
        card.appendChild(header);

        const body = document.createElement("div");
        body.className = "thinking-body";
        body.textContent = data.text || "";
        card.appendChild(body);

        state.currentTurnEventsEl.appendChild(card);
        conv.scrollTop = conv.scrollHeight;
    }

    function formatInputPreview(input) {
        if (input == null) return "";
        if (typeof input === "string") return input.slice(0, 100);
        if (typeof input === "object") {
            // Heuristic: prefer common keys
            for (const key of ["command", "file_path", "url", "query", "pattern"]) {
                if (typeof input[key] === "string") return `${key}: ${input[key]}`.slice(0, 120);
            }
            for (const v of Object.values(input)) {
                if (typeof v === "string") return v.slice(0, 100);
            }
        }
        return "";
    }

    // ===== live status footer (per chat-console#25) =====
    // CSS-only Braille spinner: 10 frames stacked, each fading in/out with a
    // staggered animation-delay. No JS animation tick — pure CSS.
    const SPINNER_FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"];

    function createStatusFooter() {
        const footer = document.createElement("div");
        footer.className = "turn-status-footer";

        const spinner = document.createElement("span");
        spinner.className = "status-spinner";
        spinner.setAttribute("aria-label", "loading");
        for (let i = 0; i < SPINNER_FRAMES.length; i++) {
            const frame = document.createElement("span");
            frame.className = "status-spinner-frame";
            frame.textContent = SPINNER_FRAMES[i];
            spinner.appendChild(frame);
        }
        footer.appendChild(spinner);

        const activity = document.createElement("span");
        activity.className = "status-activity";
        activity.textContent = "Propagating…";
        footer.appendChild(activity);

        const meta = document.createElement("span");
        meta.className = "status-meta";
        meta.textContent = "(0s · ↓0 tokens)";
        footer.appendChild(meta);

        return footer;
    }

    function updateActivity(label) {
        state.activityLabel = label;
        if (!state.statusFooterEl) return;
        const a = state.statusFooterEl.querySelector(".status-activity");
        if (a) a.textContent = label;
    }

    function tickStatus() {
        if (!state.statusFooterEl || !state.turnId) return;
        if (state.statusFooterEl.classList.contains("completed")) return;
        const elapsed = Math.floor((Date.now() - state.turnStartedAt) / 1000);
        const tokensStr = formatTokenCount(state.currentTurnOutputTokens || 0);

        // After 2s of silence, soften the activity label to "Propagating…".
        const sinceLast = Date.now() - (state.lastEventAt || state.turnStartedAt);
        let label = state.activityLabel;
        if (sinceLast > 2000 && label !== "Propagating…") {
            label = "Propagating…";
        }

        const meta = state.statusFooterEl.querySelector(".status-meta");
        if (meta) meta.textContent = `(${elapsed}s · ↓${tokensStr} tokens)`;
        const a = state.statusFooterEl.querySelector(".status-activity");
        if (a && a.textContent !== label) a.textContent = label;
    }

    function formatTokenCount(n) {
        if (n >= 1000) return (n / 1000).toFixed(1) + "k";
        return String(n);
    }

    function renderInlineError(target, text) {
        const e = document.createElement("div");
        e.className = "notice hard";
        e.textContent = text;
        (target || conv).appendChild(e);
    }

    // ===== meter =====
    // Nominal context budget comes from the server (/sessions/{id} payload),
    // not a hardcoded client constant — keeps the divisor configurable via
    // CONSOLE_NOMINAL_CONTEXT env var. Per chat-console#31. Falls back to 800K
    // (current default) if the server hasn't been reached yet.
    function renderMeter() {
        if (!state.latestUsage) {
            meter.innerHTML = `<span class="muted">${state.sessionId ? "session active" : "no session yet"}</span>`;
            return;
        }
        const u = state.latestUsage;
        const tokens = u.total_input_tokens || u.last_input_tokens || 0;
        const nominal = u.nominal_context || 800_000;
        const pct = Math.round((tokens / nominal) * 100);
        let cls = "";
        if (pct >= 95) cls = "hard";
        else if (pct >= 75) cls = "warn";
        const cost = u.total_cost_usd != null ? `$${Number(u.total_cost_usd).toFixed(4)}` : null;

        let html = `<span class="${cls}">ctx: ${tokens.toLocaleString()}/${nominal.toLocaleString()} (${pct}%)</span>`;
        if (cost) html += `<span class="muted">cost: ${cost}</span>`;
        if (u.advice) html += `<span class="advice ${u.is_above_hard ? "hard" : ""}">${escapeHtml(u.advice)}</span>`;
        meter.innerHTML = html;
    }

    // ===== prompt queue indicator (per chat-console#32) =====
    // Single-slot queue. Send-while-in-flight queues; renderQueueIndicator
    // paints a compact row in the meter showing "queued" (during in-flight)
    // or "ready" (after completion, with disposition buttons).
    function renderQueueIndicator() {
        const existing = document.getElementById("queue-indicator");
        if (existing) existing.remove();
        if (!state.queuedPrompt && state.queuedAttachments.length === 0) return;

        const row = document.createElement("div");
        row.id = "queue-indicator";
        const phase = state.turnInFlight ? "queued" : "ready";
        row.className = `queue-indicator ${phase}`;

        const label = document.createElement("span");
        label.className = "queue-label";
        label.textContent = phase + ":";

        const txt = document.createElement("span");
        txt.className = "queue-text";
        txt.textContent = (state.queuedPrompt || "").slice(0, 80) +
            (state.queuedPrompt && state.queuedPrompt.length > 80 ? "…" : "");
        if (state.queuedAttachments.length > 0) {
            txt.textContent += ` [+${state.queuedAttachments.length} 📎]`;
        }

        row.append(label, txt);

        if (phase === "queued") {
            // In-flight: only allow cancel via [x]
            const x = document.createElement("button");
            x.type = "button";
            x.className = "queue-cancel";
            x.title = "Drop queued prompt";
            x.textContent = "✕";
            x.addEventListener("click", clearQueue);
            row.appendChild(x);
        } else {
            // Ready: send / edit / drop
            const send = document.createElement("button");
            send.type = "button";
            send.className = "queue-action send";
            send.textContent = "send";
            send.addEventListener("click", sendQueued);
            const edit = document.createElement("button");
            edit.type = "button";
            edit.className = "queue-action edit";
            edit.textContent = "edit";
            edit.addEventListener("click", editQueued);
            const drop = document.createElement("button");
            drop.type = "button";
            drop.className = "queue-action drop";
            drop.textContent = "drop";
            drop.addEventListener("click", clearQueue);
            row.append(send, edit, drop);
        }

        // Insert into the meter footer area for compactness.
        meter.parentNode.insertBefore(row, meter);
    }

    function clearQueue() {
        state.queuedPrompt = null;
        state.queuedAttachments = [];
        renderQueueIndicator();
    }

    async function sendQueued() {
        const prompt = state.queuedPrompt;
        const atts = state.queuedAttachments;
        state.queuedPrompt = null;
        state.queuedAttachments = [];
        // Restore the attachments into the pending pool so submitTurn picks
        // them up via the existing upload flow.
        state.pendingAttachments = atts;
        renderAttachments();
        renderQueueIndicator();
        await submitTurn(prompt || "");
    }

    function editQueued() {
        const prompt = state.queuedPrompt || "";
        const atts = state.queuedAttachments;
        state.queuedPrompt = null;
        state.queuedAttachments = [];
        state.pendingAttachments = atts;
        renderAttachments();
        input.value = prompt;
        autosizeInput();
        input.focus();
        renderQueueIndicator();
    }

    async function refreshSessionStats() {
        if (!state.sessionId) return;
        try {
            const resp = await fetch(`/sessions/${state.sessionId}`);
            if (!resp.ok) return;
            const data = await resp.json();
            // Merge into latestUsage so meter shows authoritative + advice
            state.latestUsage = {
                ...(state.latestUsage || {}),
                total_input_tokens: data.last_input_tokens,
                total_cost_usd: data.total_cost_usd,
                nominal_context: data.nominal_context,
                advice: data.advice,
                is_above_hard: data.is_above_hard,
                is_above_warn: data.is_above_warn,
            };
            renderMeter();
        } catch { /* silent */ }
    }

    // ===== chat-spawned agent runs (per chat-console#33) =====
    // Slash command `/agent <name> <prompt>` dispatches directly to the
    // agents service. Renders a synthetic block in the conversation and
    // polls for completion in the background.
    function agentsBaseUrl() {
        // The sidebar link's href is the configured agents-console URL —
        // strip the path to get the base.
        const a = document.querySelector(".sidebar-link");
        if (!a) return "";
        try {
            const u = new URL(a.href);
            return u.origin;
        } catch {
            return "";
        }
    }

    async function spawnAgentRun(name, prompt) {
        const base = agentsBaseUrl();
        if (!base) {
            renderAgentSpawnError(name, prompt, "agents URL not configured");
            return;
        }
        // Render the synthetic block immediately so JD sees the dispatch.
        const block = createAgentSpawnBlock(name, prompt);
        conv.appendChild(block);
        conv.scrollTop = conv.scrollHeight;

        let runId;
        try {
            const resp = await fetch(`${base}/agents/${encodeURIComponent(name)}/run`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt }),
            });
            if (!resp.ok) {
                const txt = await resp.text();
                setAgentSpawnError(block, `dispatch failed (${resp.status}): ${txt}`);
                return;
            }
            const body = await resp.json();
            runId = body.run_id;
            setAgentSpawnPending(block, runId);
        } catch (e) {
            setAgentSpawnError(block, `dispatch error: ${e.message}`);
            return;
        }

        // Track the run for polling.
        state.pendingAgentRuns[runId] = {
            block,
            agentName: name,
            startedAt: Date.now(),
            pollDelayMs: 2000,
        };
        scheduleAgentPoll(runId);
    }

    function createAgentSpawnBlock(name, prompt) {
        const block = document.createElement("div");
        block.className = "block agent-spawn pending";

        const header = document.createElement("div");
        header.className = "user-prompt";
        header.textContent = `/agent ${name}`;
        block.appendChild(header);

        const body = document.createElement("div");
        body.className = "agent-spawn-body";
        const meta = document.createElement("div");
        meta.className = "agent-spawn-meta";
        meta.innerHTML =
            `<span class="agent-spawn-icon">▸</span> ` +
            `Spawning <strong>${escapeHtml(name)}</strong> · ` +
            `<span class="agent-spawn-status">dispatching…</span>`;
        body.appendChild(meta);

        const promptDiv = document.createElement("div");
        promptDiv.className = "agent-spawn-prompt";
        promptDiv.textContent = prompt;
        body.appendChild(promptDiv);

        const result = document.createElement("div");
        result.className = "agent-spawn-result";
        result.style.display = "none";
        body.appendChild(result);

        block.appendChild(body);
        return block;
    }

    function setAgentSpawnPending(block, runId) {
        const status = block.querySelector(".agent-spawn-status");
        if (status) status.textContent = `pending · run ${runId.slice(0, 18)}…`;
        block.dataset.runId = runId;
    }

    function setAgentSpawnError(block, message) {
        block.classList.remove("pending");
        block.classList.add("error");
        const status = block.querySelector(".agent-spawn-status");
        if (status) status.textContent = `error: ${message}`;
    }

    function setAgentSpawnComplete(block, runRecord) {
        block.classList.remove("pending");
        block.classList.add(runRecord.status === "done" ? "done" : "error");
        const status = block.querySelector(".agent-spawn-status");
        const elapsed = runRecord.completed_at && runRecord.started_at
            ? Math.max(0, Math.round(runRecord.completed_at - runRecord.started_at))
            : "?";
        const mark = runRecord.status === "done" ? "✓" : "✗";
        const icon = block.querySelector(".agent-spawn-icon");
        if (icon) icon.textContent = mark;
        if (status) {
            status.textContent =
                `${runRecord.status} in ${elapsed}s · run ${runRecord.run_id.slice(0, 18)}…`;
        }

        const result = block.querySelector(".agent-spawn-result");
        if (result) {
            const transcript = runRecord.output || runRecord.transcript || runRecord.error || "";
            const preview = String(transcript).slice(0, 200);
            const truncated = String(transcript).length > 200;
            result.textContent = preview + (truncated ? "…" : "");
            const link = document.createElement("a");
            link.className = "agent-spawn-link";
            link.href = agentsBaseUrl() + `/agents-console#run-${runRecord.run_id}`;
            link.target = "_blank";
            link.rel = "noopener";
            link.textContent = "view full transcript →";
            result.appendChild(document.createElement("br"));
            result.appendChild(link);
            result.style.display = "";
        }

        // Banner ping if tab hidden when run completes.
        if (document.visibilityState !== "visible") {
            maybeNotify(
                `agent ${runRecord.agent_name} ${runRecord.status}`,
                String(runRecord.transcript || "").slice(0, 140),
            );
        }
    }

    function renderAgentSpawnError(name, prompt, message) {
        const block = createAgentSpawnBlock(name, prompt);
        setAgentSpawnError(block, message);
        conv.appendChild(block);
        conv.scrollTop = conv.scrollHeight;
    }

    function scheduleAgentPoll(runId) {
        const entry = state.pendingAgentRuns[runId];
        if (!entry) return;
        setTimeout(() => pollAgentRun(runId), entry.pollDelayMs);
    }

    async function pollAgentRun(runId) {
        const entry = state.pendingAgentRuns[runId];
        if (!entry) return;
        const base = agentsBaseUrl();
        try {
            const resp = await fetch(`${base}/runs/${encodeURIComponent(runId)}`);
            if (resp.status === 404) {
                setAgentSpawnError(entry.block, "run vanished from agents service");
                delete state.pendingAgentRuns[runId];
                return;
            }
            if (!resp.ok) {
                // Transient — back off and retry
                entry.pollDelayMs = Math.min(entry.pollDelayMs * 1.5, 10000);
                scheduleAgentPoll(runId);
                return;
            }
            const run = await resp.json();
            if (["done", "error", "cancelled"].includes(run.status)) {
                setAgentSpawnComplete(entry.block, run);
                delete state.pendingAgentRuns[runId];
                return;
            }
            // Still running — back off after the first 30s
            const elapsed = Date.now() - entry.startedAt;
            entry.pollDelayMs = elapsed < 30000 ? 2000 : 5000;
            scheduleAgentPoll(runId);
        } catch (e) {
            // Network blip — back off and retry
            entry.pollDelayMs = Math.min(entry.pollDelayMs * 1.5, 10000);
            scheduleAgentPoll(runId);
        }
    }

    // ===== sidebar sessions list (per chat-console#30) =====
    const sessionsEl = document.getElementById("sessions-list");

    async function refreshSessions() {
        if (!sessionsEl) return;
        try {
            const resp = await fetch("/sessions");
            if (!resp.ok) {
                sessionsEl.innerHTML = `<div class="muted">sessions unavailable</div>`;
                return;
            }
            const body = await resp.json();
            renderSessions(body.sessions || []);
        } catch (e) {
            sessionsEl.innerHTML = `<div class="muted">sessions fetch failed: ${escapeHtml(e.message)}</div>`;
        }
    }

    const LS_SESSIONS_COLLAPSED = "console.sessions.collapsed";

    function renderSessions(sessions) {
        const activeId = state.sessionId;
        // Always include the active session in the list, even if it has no
        // completed turns yet (the server-side list aggregates from
        // history_turns, which excludes new/in-flight sessions). Without
        // this, the user can switch to an old session and lose all
        // reference to the just-active one.
        if (activeId && !sessions.some((s) => s.session_id === activeId)) {
            sessions = [
                {
                    session_id: activeId,
                    title: "(new session)",
                    turn_count: 0,
                    last_activity: Date.now() / 1000,  // sort to top
                },
                ...sessions,
            ];
        }
        if (!sessions.length) {
            sessionsEl.innerHTML = "";  // truly nothing — first-ever visitor
            return;
        }
        const collapsed = localStorage.getItem(LS_SESSIONS_COLLAPSED) === "1";
        const caret = collapsed ? "▸" : "▾";
        let html =
            `<h3 class="sessions-header" data-collapsed="${collapsed ? "1" : "0"}">` +
            `<span class="sessions-caret">${caret}</span> Sessions ` +
            `<span class="muted sessions-count">(${sessions.length})</span>` +
            `</h3>`;
        if (!collapsed) {
            html += `<div class="sessions-list-rows">`;
            for (const s of sessions) {
                const isActive = s.session_id === activeId;
                const ageStr = formatAge(s.last_activity);
                const titleHtml = escapeHtml(s.title || "(no title)");
                html +=
                    `<div class="session-row${isActive ? " active" : ""}" data-session-id="${escapeHtml(s.session_id)}">` +
                    `<span class="session-title" title="${titleHtml}">${titleHtml}</span>` +
                    `<button class="session-rename" type="button" title="Rename">✎</button>` +
                    `<span class="session-meta muted">${s.turn_count}t · ${ageStr}</span>` +
                    `</div>`;
            }
            html += `</div>`;
        }
        sessionsEl.innerHTML = html;
    }

    function formatAge(unixSeconds) {
        if (!unixSeconds) return "—";
        const ageS = Math.max(0, Date.now() / 1000 - unixSeconds);
        if (ageS < 60) return "just now";
        if (ageS < 3600) return `${Math.floor(ageS / 60)}m`;
        if (ageS < 86400) return `${Math.floor(ageS / 3600)}h`;
        if (ageS < 604800) return `${Math.floor(ageS / 86400)}d`;
        return `${Math.floor(ageS / 604800)}w`;
    }

    // Click delegation: header toggles expand/collapse; row click switches
    // session; pencil click renames; active row click is a no-op (#30).
    sessionsEl?.addEventListener("click", async (e) => {
        const header = e.target.closest(".sessions-header");
        if (header) {
            const collapsed = localStorage.getItem(LS_SESSIONS_COLLAPSED) === "1";
            localStorage.setItem(LS_SESSIONS_COLLAPSED, collapsed ? "0" : "1");
            refreshSessions();  // re-render with toggled state
            return;
        }
        const renameBtn = e.target.closest(".session-rename");
        const row = e.target.closest(".session-row");
        if (!row) return;
        const sessionId = row.dataset.sessionId;
        if (renameBtn) {
            e.stopPropagation();
            beginRename(row, sessionId);
            return;
        }
        if (sessionId === state.sessionId) return;  // active — no-op
        switchSession(sessionId);
    });

    function beginRename(row, sessionId) {
        const titleEl = row.querySelector(".session-title");
        if (!titleEl || titleEl.tagName === "INPUT") return;
        const current = titleEl.textContent;
        const input = document.createElement("input");
        input.type = "text";
        input.className = "session-title-edit";
        input.value = current;
        input.maxLength = 200;
        titleEl.replaceWith(input);
        input.focus();
        input.select();

        const finish = async (commit) => {
            input.removeEventListener("blur", onBlur);
            input.removeEventListener("keydown", onKey);
            const newTitle = (commit ? input.value.trim() : current);
            // Restore display element optimistically, then refresh from server.
            const span = document.createElement("span");
            span.className = "session-title";
            span.title = newTitle;
            span.textContent = newTitle;
            input.replaceWith(span);
            if (commit && newTitle !== current) {
                try {
                    await fetch(`/sessions/${encodeURIComponent(sessionId)}`, {
                        method: "PATCH",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ title: newTitle }),
                    });
                } catch { /* swallow; refreshSessions reconciles */ }
                refreshSessions();
            }
        };
        const onBlur = () => finish(true);
        const onKey = (ev) => {
            if (ev.key === "Enter") { ev.preventDefault(); finish(true); }
            else if (ev.key === "Escape") { ev.preventDefault(); finish(false); }
        };
        input.addEventListener("blur", onBlur);
        input.addEventListener("keydown", onKey);
    }

    // In-place session switch (per #30 decision A). Clear conv DOM, swap
    // the active session_id, run restoreSession to rebuild from history.
    async function switchSession(newSessionId) {
        state.sessionId = newSessionId;
        state.turnId = null;
        state.eventOffset = 0;
        state.currentBlock = null;
        state.currentTurnEventsEl = null;
        state.currentTextBlock = null;
        state.currentTextRunBuffer = "";
        state.lastEventType = null;
        state.statusFooterEl = null;
        state.currentTurnOutputTokens = 0;
        state.latestUsage = null;
        if (state.statusTickerId) {
            clearInterval(state.statusTickerId);
            state.statusTickerId = null;
        }
        localStorage.setItem(LS_SESSION, newSessionId);
        conv.innerHTML = "";  // clear current rendering
        await restoreSession();
        refreshSessions();  // re-render to update active marker
    }

    function escapeHtml(s) {
        return String(s ?? "").replace(/[&<>"']/g, (c) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
        }[c]));
    }

    // ===== markdown renderer (marked.js, vendored, per chat-console#29) =====
    // GFM enabled — tables, strikethrough, task lists, autolinks, fenced
    // code. `breaks: true` matches GitHub/terminal-Claude behavior of
    // treating single newlines as line breaks. No HTML sanitization —
    // single-trust personal-tool design center; claude is the only source
    // of content. If the trust model ever broadens, pair with DOMPurify.
    if (typeof window.marked !== "undefined") {
        window.marked.setOptions({ gfm: true, breaks: true });
    }
    function renderMarkdown(text) {
        if (!text) return "";
        if (typeof window.marked === "undefined") {
            // Defensive: marked failed to load. Fall back to escaped plain
            // text so the response is still readable, just unformatted.
            return escapeHtml(text).replace(/\n/g, "<br>");
        }
        return window.marked.parse(text);
    }

    // ===== diagram rendering (Kroki proxy, per chat-console#36) =====
    // Code blocks tagged with a known diagram engine get replaced with
    // an inline rendered SVG (fetched from the chat console's /render/diagram
    // proxy, which talks to the local Kroki stack). Show-source toggle
    // flips between the rendered diagram and the raw fenced code.
    const DIAGRAM_ENGINES = new Set([
        "actdiag", "blockdiag", "bpmn", "bytefield", "c4plantuml", "d2",
        "dbml", "diagramsnet", "ditaa", "dot", "erd", "excalidraw",
        "graphviz", "mermaid", "nomnoml", "nwdiag", "packetdiag", "pikchr",
        "plantuml", "rackdiag", "seqdiag", "structurizr", "svgbob",
        "symbolator", "tikz", "umlet", "vega", "vegalite", "wavedrom",
        "wireviz",
    ]);

    function enhanceDiagramBlocks(rootEl) {
        if (!rootEl) return;
        const codes = rootEl.querySelectorAll("pre > code[class*=language-]");
        for (const code of codes) {
            const cls = code.className || "";
            const m = cls.match(/language-([\w-]+)/);
            if (!m) continue;
            const engine = m[1].toLowerCase();
            // Aliases — claude often emits `graphviz` or `dot` interchangeably.
            const resolved = engine === "graphviz" ? "dot" : engine;
            if (!DIAGRAM_ENGINES.has(resolved)) continue;
            const source = code.textContent;
            const pre = code.parentElement;
            replaceWithDiagram(pre, resolved, source);
        }
    }

    async function replaceWithDiagram(pre, engine, source) {
        const block = document.createElement("div");
        block.className = "diagram-block";
        block.dataset.engine = engine;

        const loading = document.createElement("div");
        loading.className = "diagram-loading muted";
        loading.textContent = `rendering ${engine}…`;
        block.appendChild(loading);
        pre.replaceWith(block);

        let svgText;
        let renderId;
        try {
            const r = await fetch("/render/diagram", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ engine, source, format: "svg" }),
            });
            if (!r.ok) {
                const err = await r.json().catch(() => ({}));
                renderDiagramFallback(block, engine, source,
                    err.error || `render failed (${r.status})`);
                return;
            }
            renderId = r.headers.get("X-Render-Id");
            svgText = await r.text();
        } catch (e) {
            renderDiagramFallback(block, engine, source, e.message);
            return;
        }

        const cleanSvg = (window.DOMPurify
            ? window.DOMPurify.sanitize(svgText, {
                  USE_PROFILES: { svg: true, svgFilters: true },
              })
            : svgText);

        block.innerHTML = "";

        const svgWrap = document.createElement("div");
        svgWrap.className = "diagram-svg";
        svgWrap.innerHTML = cleanSvg;
        block.appendChild(svgWrap);

        const bar = document.createElement("div");
        bar.className = "diagram-bar";
        const label = document.createElement("span");
        label.className = "diagram-engine";
        label.textContent = engine;

        // Content-addressable URLs (#36 follow-up): each rendered diagram
        // gets a stable URL JD can open in a new tab from any tailnet device.
        // iPhone Safari can long-press to save / share via the standard
        // share sheet from these links.
        if (renderId) {
            const open = document.createElement("a");
            open.className = "diagram-action diagram-link";
            open.href = `/render/diagram/${renderId}.svg`;
            open.target = "_blank";
            open.rel = "noopener";
            open.textContent = "open ↗";
            open.title = "Open SVG in new tab (long-press on iPhone to save/share)";

            const png = document.createElement("a");
            png.className = "diagram-action diagram-link";
            png.href = `/render/diagram/${renderId}.png`;
            png.target = "_blank";
            png.rel = "noopener";
            png.textContent = "PNG";
            png.title = "Open PNG in new tab (long-press on iPhone to save)";

            bar.append(label, open, png);
        } else {
            // Fallback: blob-download via the older path if render-id
            // header missing (shouldn't happen post-#36 follow-up).
            const dl = document.createElement("button");
            dl.className = "diagram-action";
            dl.type = "button";
            dl.textContent = "PNG";
            dl.addEventListener("click", () => downloadDiagram(engine, source, "png"));
            bar.append(label, dl);
        }

        const toggle = document.createElement("button");
        toggle.className = "diagram-action";
        toggle.type = "button";
        toggle.textContent = "show source";
        toggle.addEventListener("click", () => {
            const showing = block.classList.toggle("show-source");
            toggle.textContent = showing ? "show diagram" : "show source";
        });
        bar.append(toggle);
        block.appendChild(bar);

        const sourceEl = document.createElement("pre");
        sourceEl.className = "diagram-source code-block";
        sourceEl.dataset.lang = engine;
        const codeEl = document.createElement("code");
        codeEl.textContent = source;
        sourceEl.appendChild(codeEl);
        block.appendChild(sourceEl);
    }

    function renderDiagramFallback(block, engine, source, errMessage) {
        block.classList.add("diagram-error");
        block.innerHTML = "";
        const note = document.createElement("div");
        note.className = "diagram-error-note muted";
        note.textContent = `diagram render unavailable (${engine}): ${errMessage}`;
        block.appendChild(note);
        const pre = document.createElement("pre");
        pre.className = "code-block";
        pre.dataset.lang = engine;
        const code = document.createElement("code");
        code.textContent = source;
        pre.appendChild(code);
        block.appendChild(pre);
    }

    async function downloadDiagram(engine, source, format) {
        try {
            const r = await fetch("/render/diagram", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ engine, source, format }),
            });
            if (!r.ok) return;
            const blob = await r.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `diagram-${engine}.${format}`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch { /* swallow */ }
    }

    // Stream watchdog and visibilitychange-resume removed per chat-console#28 —
    // there's no live stream to resume. POST /turns blocks until the turn
    // completes, recovery on a dropped POST is handled by reload + history.

    // Refresh the sidebar sessions list when the tab becomes visible again
    // (covers backgrounded-tab + multi-tab cases where the list could go
    // stale between turn-completion events). Cheap GET, no side-effects.
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            refreshSessions();
        }
    });

    // ===== Wake Lock — keep screen alive while a turn is generating =====
    async function acquireWakeLock() {
        if (!("wakeLock" in navigator)) return;
        if (state.wakeLock) return;
        try {
            state.wakeLock = await navigator.wakeLock.request("screen");
            state.wakeLock.addEventListener("release", () => {
                state.wakeLock = null;
            });
        } catch {
            // permission denied / unsupported / battery saver — ignore
        }
    }

    async function releaseWakeLock() {
        if (!state.wakeLock) return;
        try { await state.wakeLock.release(); } catch { /* */ }
        state.wakeLock = null;
    }

    // ===== Notifications — banner ping when a long turn finishes while hidden =====
    function notificationsAvailable() {
        return "Notification" in window;
    }

    function updateNotifButton() {
        if (!notificationsAvailable()) return;
        if (Notification.permission === "default") {
            notifBtn.hidden = false;
            notifBtn.title = "Enable notifications";
        } else {
            notifBtn.hidden = true;
        }
    }

    if (notifBtn) {
        notifBtn.addEventListener("click", async () => {
            if (!notificationsAvailable()) return;
            try { await Notification.requestPermission(); } catch { /* */ }
            updateNotifButton();
        });
    }
    updateNotifButton();

    async function maybeNotify(title, body) {
        if (document.visibilityState === "visible") return;
        if (!notificationsAvailable()) return;
        if (Notification.permission !== "granted") return;
        const opts = {
            body,
            icon: "/static/avatar.png",
            tag: "turn-complete",
            silent: false,
        };
        try {
            // PWA path (iOS): use SW registration if we have one
            if (state.swRegistration && state.swRegistration.showNotification) {
                await state.swRegistration.showNotification(title, opts);
                return;
            }
            // Desktop fallback
            new Notification(title, opts);
        } catch {
            // Notifications can fail in private browsing, etc. Silent.
        }
    }

    // ===== Service Worker registration =====
    async function registerServiceWorker() {
        if (!("serviceWorker" in navigator)) return;
        try {
            state.swRegistration = await navigator.serviceWorker.register("/sw.js", {
                scope: "/",
            });
        } catch {
            // SW registration failure isn't fatal — chat still works without PWA.
        }
    }

    // ===== session restore (per chat-console#27, simplified for #28) =====
    // On page load, fetch the session's turn list and rehydrate. With the
    // synchronous wire (#28), there's no in-flight turn to live-attach —
    // any turn that didn't make it to history is gone (the browser POST
    // either completed or was orphaned; orphaned ones complete server-side
    // and land in history, picked up on the NEXT reload).
    async function restoreSession() {
        const sessionId = localStorage.getItem(LS_SESSION);
        if (!sessionId) return;
        let body;
        try {
            const resp = await fetch(
                `/sessions/${encodeURIComponent(sessionId)}/turns`
            );
            if (!resp.ok) return;
            body = await resp.json();
        } catch {
            return;
        }
        const turns = (body && body.turns) || [];
        if (!turns.length) return;
        for (const t of turns) {
            await replayOneTurn(sessionId, t);
        }
        conv.scrollTop = conv.scrollHeight;
    }

    async function replayOneTurn(sessionId, summary) {
        const block = document.createElement("div");
        block.className = "block";

        const userP = document.createElement("div");
        userP.className = "user-prompt";
        userP.textContent = summary.prompt || "";
        block.appendChild(userP);

        const turnEvents = document.createElement("div");
        turnEvents.className = "turn-events";
        block.appendChild(turnEvents);

        const footer = createStatusFooter();
        block.appendChild(footer);

        conv.appendChild(block);

        // Set per-turn state so handleEvent knows where to render.
        state.currentBlock = block;
        state.currentTurnEventsEl = turnEvents;
        state.currentTextBlock = null;
        state.currentTextRunBuffer = "";
        state.lastEventType = null;
        state.statusFooterEl = footer;
        state.turnStartedAt = (summary.started_at || 0) * 1000;
        state.activityLabel = "Propagating…";
        state.currentTurnOutputTokens = 0;
        state.eventOffset = 0;

        // Pull events from history. Buffer-sourced turns are also fetched
        // via the same endpoint — list_session_turns includes both, and
        // the per-turn detail endpoint reads from history.
        let events = [];
        try {
            const r = await fetch(
                `/sessions/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(summary.turn_id)}`
            );
            if (r.ok) events = (await r.json()).events || [];
        } catch { /* network blip — render an empty turn rather than crash */ }

        for (const evt of events) {
            handleEvent(evt);
            state.eventOffset += 1;
        }

        // Finalize the footer with completion summary (matches the live
        // onTurnComplete path).
        if (state.currentTextBlock) {
            state.currentTextBlock.classList.remove("streaming");
            enhanceDiagramBlocks(state.currentTextBlock);  // #36
            state.currentTextBlock = null;
            state.currentTextRunBuffer = "";
        }
        const elapsed = summary.completed_at && summary.started_at
            ? Math.max(0, Math.floor(summary.completed_at - summary.started_at))
            : 0;
        const tokensStr = formatTokenCount(state.currentTurnOutputTokens || 0);
        footer.classList.add("completed");
        footer.innerHTML = "";
        const span = document.createElement("span");
        span.className = "status-completed";
        span.textContent = `completed in ${elapsed}s · ↓${tokensStr} tokens`;
        footer.appendChild(span);
    }

    // ===== boot =====
    registerServiceWorker();
    renderMeter();
    refreshSessions();
    restoreSession();  // fire-and-forget — populates conv as turns render
})();
