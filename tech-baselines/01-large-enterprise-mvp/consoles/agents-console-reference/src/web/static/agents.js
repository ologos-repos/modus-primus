// Fleet panel — slots into the existing console sidebar.
// Lists agent specs + recent runs. Click a card to open a modal:
//  - agent → spec view + spawn-with-prompt input
//  - run   → status + transcript (replayed via SSE)

(() => {
    "use strict";

    const REFRESH_INTERVAL_MS = 5_000;

    const fleetPanel = document.getElementById("fleet-panel");
    if (!fleetPanel) {
        // No mounting point — index.html doesn't include the fleet panel slot.
        // Disable silently rather than throw.
        return;
    }

    let lastAgents = [];
    let lastRuns = [];
    let lastApprovals = [];
    let lastServices = [];
    let lastWorkflows = [];
    let lastWorkflowRuns = [];
    let lastTriggers = [];

    // ---- rendering ----

    function escapeHtml(s) {
        return String(s ?? "").replace(/[&<>"']/g, c => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
        }[c]));
    }

    function ageString(ts) {
        if (!ts) return "—";
        const seconds = Math.max(0, (Date.now() / 1000) - ts);
        if (seconds < 60) return `${Math.floor(seconds)}s`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
        return `${Math.floor(seconds / 86400)}d`;
    }

    function humanizeCron(expr) {
        // Best-effort plain-English for the common patterns we expect.
        const parts = (expr || "").trim().split(/\s+/);
        if (parts.length !== 5) return expr;
        const [m, h, dom, mo, dow] = parts;
        if (m === "*" && h === "*" && dom === "*" && mo === "*" && dow === "*") return "every minute";
        const stepMatch = m.match(/^\*\/(\d+)$/);
        if (stepMatch && h === "*" && dom === "*" && mo === "*" && dow === "*") return `every ${stepMatch[1]} minutes`;
        if (m === "0" && /^\d+$/.test(h) && dom === "*" && mo === "*" && dow === "*") return `daily at ${String(h).padStart(2, "0")}:00`;
        if (/^\d+$/.test(m) && /^\d+$/.test(h) && dom === "*" && mo === "*" && dow === "*") return `daily at ${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
        return expr;
    }

    function statusMark(status) {
        return ({
            done: "✓", error: "✗", cancelled: "·",
            running: "▸", pending: "○",
        })[status] || "?";
    }

    // ===== collapsible section wrappers (per [ENTERPRISE: tracker ref]) =====
    const LS_COLLAPSE_PREFIX = "agents.collapsed.";

    function isCollapsed(key) {
        return localStorage.getItem(LS_COLLAPSE_PREFIX + key) === "1";
    }

    function section(key, label, count, body) {
        const collapsed = isCollapsed(key);
        const caret = collapsed ? "▸" : "▾";
        const collapsedAttr = collapsed ? ' data-collapsed="1"' : "";
        return (
            `<div class="ac-section"${collapsedAttr} data-section="${escapeHtml(key)}">` +
              `<h3 class="ac-section-header" data-section-key="${escapeHtml(key)}">` +
                `<span class="ac-caret">${caret}</span> ` +
                `${escapeHtml(label)} ` +
                (count != null ? `<span class="ac-count">(${count})</span>` : "") +
              `</h3>` +
              `<div class="ac-section-body">${body}</div>` +
            `</div>`
        );
    }

    function render() {
        const agents = lastAgents;
        const runs = lastRuns;
        const approvals = lastApprovals;
        const services = lastServices;
        const workflows = lastWorkflows;
        const workflowRuns = lastWorkflowRuns;
        const triggers = lastTriggers;

        let html = "";

        if (approvals.length) {
            let body = "";
            for (const r of approvals) {
                body += `<div class="approval-card" data-run-id="${escapeHtml(r.run_id)}">`;
                body += `<div class="approval-header">`;
                body += `<span class="agent">${escapeHtml(r.agent_name)}</span>`;
                body += `<span class="age">${ageString(r.started_at)} ago</span>`;
                body += `</div>`;
                body += `<div class="approval-prompt">${escapeHtml((r.prompt || "").slice(0, 140))}${(r.prompt || "").length > 140 ? "…" : ""}</div>`;
                body += `<div class="approval-actions">`;
                body += `<button class="approve-btn" data-run-id="${escapeHtml(r.run_id)}">approve</button>`;
                body += `<button class="deny-btn" data-run-id="${escapeHtml(r.run_id)}">deny</button>`;
                body += `</div>`;
                body += `</div>`;
            }
            html += section("approvals", "⚠ Pending approvals", approvals.length, body);
        }

        // Recent runs gets promoted up the page — that's the section JD
        // checks most often, and on iPhone it was buried at the bottom.
        if (runs.length) {
            let body = "";
            for (const r of runs) {
                body += `<div class="run-card" data-status="${escapeHtml(r.status)}" data-run-id="${escapeHtml(r.run_id)}">`;
                body += `<span class="mark">${statusMark(r.status)}</span>`;
                body += `<span class="agent">${escapeHtml(r.agent_name)}</span>`;
                if (r.qa_outcome) {
                    const qaCls = r.qa_outcome === "pass" ? "qa-pass"
                                : r.qa_outcome === "fail" ? "qa-fail"
                                : "qa-error";
                    const qaMark = r.qa_outcome === "pass" ? "QA✓" : "QA✗";
                    body += `<span class="qa-mark ${qaCls}" title="${escapeHtml(r.qa_reason || r.qa_outcome)}">${qaMark}</span>`;
                }
                body += `<span class="age">${ageString(r.completed_at || r.started_at)}</span>`;
                body += `</div>`;
            }
            html += section("recent-runs", "Recent runs", runs.length, body);
        }

        if (agents.length) {
            // Group agents by domain (per #34). Each domain becomes a
            // collapsible sub-header within the Agents section.
            const byDomain = {};
            for (const a of agents) {
                const d = a.domain || "uncategorized";
                (byDomain[d] = byDomain[d] || []).push(a);
            }
            const domainNames = Object.keys(byDomain).sort();
            let agentsBody = "";
            for (const d of domainNames) {
                const domainAgents = byDomain[d].slice().sort((x, y) => x.name.localeCompare(y.name));
                let domainBody = "";
                for (const a of domainAgents) {
                    const forkCls = a.fork === "infraops" ? "fork-ops" : "fork-dev";
                    const provider = (a.provider || "claude").toLowerCase();
                    domainBody += `<div class="agent-card ${forkCls}" data-name="${escapeHtml(a.name)}" data-fork="${escapeHtml(a.fork)}">`;
                    domainBody += `<span class="fork-badge ${forkCls}">${a.fork === "infraops" ? "OPS" : "DEV"}</span>`;
                    if (provider !== "claude") {
                        domainBody += `<span class="provider-chip provider-${escapeHtml(provider)}">${escapeHtml(provider)}</span>`;
                    }
                    domainBody += `<span class="name">${escapeHtml(a.name)}</span>`;
                    domainBody += `<button class="run-btn" data-action="run" data-name="${escapeHtml(a.name)}">run</button>`;
                    domainBody += `</div>`;
                }
                agentsBody += section("agents-domain-" + d, d, domainAgents.length, domainBody);
            }
            html += section("agents", "Agents", agents.length, agentsBody);
        }

        if (workflows.length) {
            let body = "";
            for (const wf of workflows) {
                body += `<div class="workflow-card" data-name="${escapeHtml(wf.name)}">`;
                body += `<span class="wf-icon">⚡</span>`;
                body += `<span class="name">${escapeHtml(wf.name)}</span>`;
                body += `<span class="step-count">${wf.step_count} step${wf.step_count === 1 ? "" : "s"}</span>`;
                body += `</div>`;
            }
            html += section("workflows", "Workflows", workflows.length, body);
        }

        if (workflowRuns.length) {
            let body = "";
            for (const wr of workflowRuns) {
                body += `<div class="workflow-run-card" data-status="${escapeHtml(wr.status)}" data-id="${escapeHtml(wr.workflow_run_id)}">`;
                body += `<span class="mark">${statusMark(wr.status)}</span>`;
                body += `<span class="workflow">${escapeHtml(wr.workflow_name)}</span>`;
                body += `<span class="age">${ageString(wr.completed_at || wr.started_at)}</span>`;
                body += `</div>`;
            }
            html += section("workflow-runs", "Workflow runs", workflowRuns.length, body);
        }

        if (triggers.length) {
            let body = "";
            for (const t of triggers) {
                const lastFired = t.last_fired_at ? `${ageString(t.last_fired_at)} ago` : "never";
                body += `<div class="trigger-card" data-name="${escapeHtml(t.name)}">`;
                body += `<span class="cron-chip">${escapeHtml(humanizeCron(t.schedule))}</span>`;
                body += `<span class="name">${escapeHtml(t.name)}</span>`;
                body += `<span class="target">→ ${escapeHtml(t.target_kind)}/${escapeHtml(t.target)}</span>`;
                body += `<span class="last-fired">${lastFired}</span>`;
                body += `<button class="fire-btn" data-action="fire" data-name="${escapeHtml(t.name)}">fire</button>`;
                body += `</div>`;
            }
            html += section("triggers", "Triggers", triggers.length, body);
        }

        if (services.length) {
            let body = "";
            for (const svc of services) {
                const state = svc.status?.active_state || "unknown";
                const dotCls = state === "active" ? "active"
                             : state === "failed" ? "failed"
                             : "inactive";
                body += `<div class="service-card" data-status="${escapeHtml(state)}" data-name="${escapeHtml(svc.name)}">`;
                body += `<span class="service-status-dot ${dotCls}" title="${escapeHtml(state)}"></span>`;
                body += `<span class="name">${escapeHtml(svc.name)}</span>`;
                body += `<span class="unit">${escapeHtml(svc.unit)}</span>`;
                body += `</div>`;
            }
            html += section("services", "Services", services.length, body);
        }

        if (!html) {
            html = `<h3>Fleet</h3><div class="muted">no agents or runs yet</div>`;
        }

        fleetPanel.innerHTML = html;
    }

    fleetPanel.addEventListener("click", (e) => {
        const target = e.target;
        // Collapsible section header — toggle and persist (#34)
        const header = target.closest(".ac-section-header");
        if (header) {
            const key = header.dataset.sectionKey;
            const sec = header.parentElement;
            const wasCollapsed = sec.dataset.collapsed === "1";
            if (wasCollapsed) {
                delete sec.dataset.collapsed;
                localStorage.removeItem(LS_COLLAPSE_PREFIX + key);
            } else {
                sec.dataset.collapsed = "1";
                localStorage.setItem(LS_COLLAPSE_PREFIX + key, "1");
            }
            const caret = header.querySelector(".ac-caret");
            if (caret) caret.textContent = wasCollapsed ? "▾" : "▸";
            return;
        }
        if (target.matches(".approve-btn")) {
            e.stopPropagation();
            decideApproval(target.dataset.runId, "approve");
            return;
        }
        if (target.matches(".deny-btn")) {
            e.stopPropagation();
            decideApproval(target.dataset.runId, "deny");
            return;
        }
        if (target.matches(".run-btn")) {
            e.stopPropagation();
            const name = target.dataset.name;
            promptAndSpawn(name);
            return;
        }
        if (target.matches(".fire-btn")) {
            e.stopPropagation();
            fireTriggerNow(target.dataset.name);
            return;
        }
        const agentCard = target.closest(".agent-card");
        if (agentCard) {
            const name = agentCard.dataset.name;
            openAgentModal(name);
            return;
        }
        const serviceCard = target.closest(".service-card");
        if (serviceCard) {
            openServiceModal(serviceCard.dataset.name);
            return;
        }
        const workflowCard = target.closest(".workflow-card");
        if (workflowCard) {
            openWorkflowModal(workflowCard.dataset.name);
            return;
        }
        const workflowRunCard = target.closest(".workflow-run-card");
        if (workflowRunCard) {
            openWorkflowRunModal(workflowRunCard.dataset.id);
            return;
        }
        const triggerCard = target.closest(".trigger-card");
        if (triggerCard) {
            openTriggerModal(triggerCard.dataset.name);
            return;
        }
        // Approval card not yet handled separately — clicking outside the
        // buttons does nothing (avoids accidental actions).
        if (target.closest(".approval-card")) return;
        const runCard = target.closest(".run-card");
        if (runCard) {
            const runId = runCard.dataset.runId;
            openRunModal(runId);
        }
    });

    async function decideApproval(runId, decision) {
        const reason = window.prompt(
            decision === "approve"
                ? "Approval reason (optional):"
                : "Denial reason (required):"
        );
        if (decision === "deny" && (reason === null || !reason.trim())) {
            return;  // cancelled
        }
        try {
            await fetch(`/runs/${encodeURIComponent(runId)}/${decision}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    approver: "console-user",
                    reason: (reason || "").trim(),
                }),
            });
            refresh();
        } catch (e) {
            window.alert(`Failed: ${e.message}`);
        }
    }

    // ---- API + refresh ----

    async function refresh() {
        try {
            const [agentsResp, runsResp, approvalsResp, servicesResp, wfResp, wfRunsResp, triggersResp] = await Promise.all([
                fetch("/agents"),
                fetch("/runs?limit=10"),
                fetch("/approvals"),
                fetch("/services"),
                fetch("/workflows"),
                fetch("/workflow-runs?limit=10"),
                fetch("/triggers"),
            ]);
            if (agentsResp.ok) lastAgents = await agentsResp.json();
            if (runsResp.ok) lastRuns = await runsResp.json();
            if (approvalsResp.ok) lastApprovals = await approvalsResp.json();
            if (servicesResp.ok) lastServices = await servicesResp.json();
            if (wfResp.ok) lastWorkflows = await wfResp.json();
            if (wfRunsResp.ok) lastWorkflowRuns = await wfRunsResp.json();
            if (triggersResp.ok) lastTriggers = await triggersResp.json();
            render();
        } catch (e) {
            // Likely the means.agents extension isn't enabled (404 on routes).
            // Hide the panel gracefully.
            fleetPanel.innerHTML = "";
        }
    }

    // ---- modal ----

    function openModal({ title, meta, bodyHtml, onMount }) {
        const backdrop = document.createElement("div");
        backdrop.className = "fleet-modal-backdrop";
        backdrop.innerHTML = `
            <div class="fleet-modal" role="dialog">
              <div class="fleet-modal-header">
                <span class="fleet-modal-title">${escapeHtml(title)}</span>
                <span class="fleet-modal-meta">${meta || ""}</span>
                <button class="fleet-modal-close" aria-label="close">close</button>
              </div>
              <div class="fleet-modal-body">${bodyHtml}</div>
            </div>`;
        const close = () => backdrop.remove();
        backdrop.addEventListener("click", (e) => {
            if (e.target === backdrop || e.target.matches(".fleet-modal-close")) close();
        });
        document.addEventListener("keydown", function esc(e) {
            if (e.key === "Escape") {
                close();
                document.removeEventListener("keydown", esc);
            }
        });
        document.body.appendChild(backdrop);
        if (onMount) onMount(backdrop);
        return { close, backdrop };
    }

    async function openAgentModal(name) {
        let spec;
        try {
            const resp = await fetch(`/agents/${encodeURIComponent(name)}`);
            if (!resp.ok) {
                openModal({ title: name, meta: "", bodyHtml: `<div>error: ${resp.status}</div>` });
                return;
            }
            spec = await resp.json();
        } catch (e) {
            openModal({ title: name, meta: "", bodyHtml: `<div>fetch failed: ${escapeHtml(e.message)}</div>` });
            return;
        }

        const bodyHtml = `
          <div class="fleet-modal-section">
            <h4>Spec</h4>
            <div>fork: <code>${escapeHtml(spec.fork)}</code> · model: <code>${escapeHtml(spec.model)}</code> · timeout: ${escapeHtml(String(spec.timeout_s))}s</div>
            <div class="muted">spec_hash: <code>${escapeHtml((spec.spec_hash || "").slice(0, 12))}…</code></div>
          </div>
          <div class="fleet-modal-section">
            <h4>System prompt</h4>
            <pre>${escapeHtml(spec.system_prompt || "")}</pre>
          </div>
          <div class="spawn-row">
            <input type="text" class="spawn-input" placeholder="prompt">
            <button class="spawn-btn">spawn</button>
          </div>
        `;
        openModal({
            title: name,
            meta: spec.domain || "",
            bodyHtml,
            onMount: (root) => {
                const input = root.querySelector(".spawn-input");
                const btn = root.querySelector(".spawn-btn");
                const fire = async () => {
                    const prompt = input.value.trim();
                    if (!prompt) return;
                    btn.disabled = true;
                    btn.textContent = "spawning…";
                    try {
                        const resp = await fetch(`/agents/${encodeURIComponent(name)}/run`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ prompt }),
                        });
                        if (resp.ok) {
                            root.remove();
                            refresh();
                        } else {
                            btn.textContent = `error ${resp.status}`;
                        }
                    } catch (e) {
                        btn.textContent = "network error";
                    }
                };
                btn.addEventListener("click", fire);
                input.addEventListener("keydown", (e) => {
                    if (e.key === "Enter") fire();
                });
                input.focus();
            },
        });
    }

    async function openServiceModal(name) {
        let svc;
        try {
            const resp = await fetch(`/services/${encodeURIComponent(name)}`);
            if (!resp.ok) {
                openModal({ title: name, meta: "", bodyHtml: `<div>error: ${resp.status}</div>` });
                return;
            }
            svc = await resp.json();
        } catch (e) {
            openModal({ title: name, meta: "", bodyHtml: `<div>fetch failed: ${escapeHtml(e.message)}</div>` });
            return;
        }
        const status = svc.status || {};
        const memMB = status.memory_bytes ? (status.memory_bytes / (1024 * 1024)).toFixed(1) : "—";
        const logsHtml = (svc.logs || []).map(l => escapeHtml(l)).join("\n") || "(no recent log lines)";
        const bodyHtml = `
          <div class="fleet-modal-section">
            <h4>Status</h4>
            <div>state: <code>${escapeHtml(status.active_state || "unknown")}</code>${status.sub_state ? ` · sub: <code>${escapeHtml(status.sub_state)}</code>` : ""}</div>
            <div>unit: <code>${escapeHtml(svc.unit)}</code> · scope: <code>${escapeHtml(svc.scope)}</code></div>
            <div>pid: <code>${escapeHtml(String(status.main_pid || "—"))}</code> · memory: <code>${escapeHtml(memMB)} MB</code>${status.result ? ` · result: <code>${escapeHtml(status.result)}</code>` : ""}</div>
            ${status.started_at ? `<div class="muted">started: ${escapeHtml(status.started_at)}</div>` : ""}
          </div>
          <div class="fleet-modal-section">
            <h4>Purpose</h4>
            <div>${escapeHtml(svc.purpose || "")}</div>
          </div>
          <div class="fleet-modal-section">
            <h4>Recent journal</h4>
            <pre class="service-logs">${logsHtml}</pre>
          </div>
        `;
        openModal({
            title: name,
            meta: svc.unit,
            bodyHtml,
        });
    }

    async function openWorkflowModal(name) {
        let wf;
        try {
            const resp = await fetch(`/workflows/${encodeURIComponent(name)}`);
            if (!resp.ok) {
                openModal({ title: name, meta: "", bodyHtml: `<div>error: ${resp.status}</div>` });
                return;
            }
            wf = await resp.json();
        } catch (e) {
            openModal({ title: name, meta: "", bodyHtml: `<div>fetch failed: ${escapeHtml(e.message)}</div>` });
            return;
        }
        const stepsHtml = wf.steps.map((s, i) => `
            <div class="workflow-step-row">
              <span class="step-idx">${i + 1}</span>
              <span class="step-id">${escapeHtml(s.id)}</span>
              <span class="step-arrow">→</span>
              <code>${escapeHtml(s.agent)}</code>
              <div class="step-prompt"><code>${escapeHtml(s.prompt)}</code></div>
            </div>
        `).join("");
        const bodyHtml = `
          <div class="fleet-modal-section">
            <h4>Description</h4>
            <div>${escapeHtml(wf.description || "(no description)")}</div>
          </div>
          <div class="fleet-modal-section">
            <h4>Steps (${wf.step_count})</h4>
            ${stepsHtml}
          </div>
          <div class="spawn-row">
            <input type="text" class="spawn-input" placeholder="initial input">
            <button class="spawn-btn">spawn</button>
          </div>
        `;
        openModal({
            title: name,
            meta: `${wf.step_count} step${wf.step_count === 1 ? "" : "s"}`,
            bodyHtml,
            onMount: (root) => {
                const input = root.querySelector(".spawn-input");
                const btn = root.querySelector(".spawn-btn");
                const fire = async () => {
                    const prompt = input.value.trim();
                    if (!prompt) return;
                    btn.disabled = true;
                    btn.textContent = "spawning…";
                    try {
                        const resp = await fetch(`/workflows/${encodeURIComponent(name)}/run`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ prompt }),
                        });
                        if (resp.ok) {
                            root.remove();
                            refresh();
                        } else {
                            btn.textContent = `error ${resp.status}`;
                        }
                    } catch (e) {
                        btn.textContent = "network error";
                    }
                };
                btn.addEventListener("click", fire);
                input.addEventListener("keydown", (e) => {
                    if (e.key === "Enter") fire();
                });
                input.focus();
            },
        });
    }

    async function openWorkflowRunModal(workflowRunId) {
        let wr;
        try {
            const resp = await fetch(`/workflow-runs/${encodeURIComponent(workflowRunId)}`);
            if (!resp.ok) {
                openModal({ title: workflowRunId, meta: "", bodyHtml: `<div>error: ${resp.status}</div>` });
                return;
            }
            wr = await resp.json();
        } catch (e) {
            openModal({ title: workflowRunId, meta: "", bodyHtml: `<div>fetch failed: ${escapeHtml(e.message)}</div>` });
            return;
        }
        const steps = wr.steps || [];
        const stepsHtml = steps.length ? steps.map((s, i) => `
            <div class="workflow-step-run-row" data-status="${escapeHtml(s.status)}" data-run-id="${escapeHtml(s.run_id)}">
              <span class="step-idx">${i + 1}</span>
              <span class="mark">${statusMark(s.status)}</span>
              <span class="agent">${escapeHtml(s.agent_name)}</span>
              ${s.qa_outcome ? `<span class="qa-mark qa-${escapeHtml(s.qa_outcome)}">QA${s.qa_outcome === "pass" ? "✓" : "✗"}</span>` : ""}
              <span class="age">${ageString(s.completed_at || s.started_at)}</span>
            </div>
        `).join("") : "<div class=\"muted\">(no steps started yet)</div>";
        const bodyHtml = `
          <div class="fleet-modal-section">
            <h4>Status</h4>
            <div>state: <code>${escapeHtml(wr.status)}</code></div>
            ${wr.error ? `<div class="error">error: ${escapeHtml(wr.error)}</div>` : ""}
          </div>
          <div class="fleet-modal-section">
            <h4>Initial input</h4>
            <pre>${escapeHtml(wr.prompt || "")}</pre>
          </div>
          <div class="fleet-modal-section">
            <h4>Steps (${steps.length})</h4>
            ${stepsHtml}
          </div>
          ${wr.final_output ? `<div class="fleet-modal-section"><h4>Final output</h4><pre>${escapeHtml(wr.final_output)}</pre></div>` : ""}
        `;
        openModal({
            title: wr.workflow_name,
            meta: workflowRunId.slice(-8),
            bodyHtml,
            onMount: (root) => {
                root.addEventListener("click", (e) => {
                    const stepRow = e.target.closest(".workflow-step-run-row");
                    if (stepRow) {
                        root.remove();
                        openRunModal(stepRow.dataset.runId);
                    }
                });
            },
        });
    }

    async function fireTriggerNow(name) {
        try {
            await fetch(`/triggers/${encodeURIComponent(name)}/fire`, {
                method: "POST",
            });
            refresh();
        } catch (e) {
            window.alert(`Fire failed: ${e.message}`);
        }
    }

    async function openTriggerModal(name) {
        let t;
        try {
            const resp = await fetch(`/triggers/${encodeURIComponent(name)}`);
            if (!resp.ok) {
                openModal({ title: name, meta: "", bodyHtml: `<div>error: ${resp.status}</div>` });
                return;
            }
            t = await resp.json();
        } catch (e) {
            openModal({ title: name, meta: "", bodyHtml: `<div>fetch failed: ${escapeHtml(e.message)}</div>` });
            return;
        }
        const lastFired = t.last_fired_at
            ? `${ageString(t.last_fired_at)} ago`
            : "(never)";
        const nextFire = t.next_fire_at
            ? `in ${ageString(t.next_fire_at)} from now (≈ ${new Date(t.next_fire_at * 1000).toLocaleTimeString()})`
            : "(unknown)";
        const bodyHtml = `
          <div class="fleet-modal-section">
            <h4>Schedule</h4>
            <div><code>${escapeHtml(t.schedule)}</code> — ${escapeHtml(humanizeCron(t.schedule))}</div>
            <div class="muted">last fired: ${lastFired} (count: ${t.fire_count})</div>
            <div class="muted">next fire: ${nextFire}</div>
          </div>
          <div class="fleet-modal-section">
            <h4>Target</h4>
            <div>${escapeHtml(t.target_kind)}: <code>${escapeHtml(t.target)}</code></div>
            <div class="muted">prompt: ${escapeHtml(t.prompt)}</div>
          </div>
          <div class="fleet-modal-section">
            <h4>Description</h4>
            <div>${escapeHtml(t.description || "(none)")}</div>
          </div>
          <div class="spawn-row">
            <button class="spawn-btn fire-now-btn">fire now</button>
          </div>
        `;
        openModal({
            title: name,
            meta: humanizeCron(t.schedule),
            bodyHtml,
            onMount: (root) => {
                root.querySelector(".fire-now-btn").addEventListener("click", async () => {
                    await fireTriggerNow(name);
                    root.remove();
                });
            },
        });
    }

    async function openRunModal(runId) {
        let run;
        try {
            const resp = await fetch(`/runs/${encodeURIComponent(runId)}`);
            if (!resp.ok) return;
            run = await resp.json();
        } catch {
            return;
        }

        let qaBlock = "";
        if (run.qa_outcome) {
            const qaCls = run.qa_outcome === "pass" ? "qa-pass"
                        : run.qa_outcome === "fail" ? "qa-fail"
                        : "qa-error";
            qaBlock = `
              <div class="fleet-modal-section">
                <h4>QA</h4>
                <div class="${qaCls}">
                  <strong>${escapeHtml(run.qa_outcome.toUpperCase())}</strong>
                  ${run.qa_reason ? ` — ${escapeHtml(run.qa_reason)}` : ""}
                </div>
              </div>
            `;
        }

        const bodyHtml = `
          <div class="fleet-modal-section">
            <h4>Run</h4>
            <div>agent: <code>${escapeHtml(run.agent_name)}</code> · status: <code>${escapeHtml(run.status)}</code> · started ${ageString(run.started_at)} ago</div>
            ${run.error ? `<div style="color:var(--error)">error: ${escapeHtml(run.error)}</div>` : ""}
            ${run.cost_usd ? `<div class="muted">cost: $${Number(run.cost_usd).toFixed(4)}</div>` : ""}
          </div>
          ${qaBlock}
          <div class="fleet-modal-section">
            <h4>Prompt</h4>
            <pre>${escapeHtml(run.prompt)}</pre>
          </div>
          <div class="fleet-modal-section">
            <h4>Transcript</h4>
            <div class="fleet-events"></div>
          </div>
        `;
        const { backdrop, close } = openModal({
            title: run.agent_name,
            meta: run.run_id,
            bodyHtml,
        });
        const events = backdrop.querySelector(".fleet-events");
        const es = new EventSource(`/runs/${encodeURIComponent(runId)}/stream`);
        es.onmessage = (e) => {
            let evt;
            try { evt = JSON.parse(e.data); } catch { return; }
            const div = document.createElement("div");
            div.className = "fleet-event";
            div.dataset.type = evt.type || "?";
            const t = (evt.type === "token" && evt.data && evt.data.text) ? evt.data.text
                    : JSON.stringify(evt.data, null, 2);
            div.innerHTML = `<span class="event-type">${escapeHtml(evt.type || "?")}</span> <span class="event-data">${escapeHtml(t)}</span>`;
            events.appendChild(div);
        };
        es.addEventListener("status", (e) => {
            let payload = {};
            try { payload = JSON.parse(e.data); } catch { /* */ }
            const div = document.createElement("div");
            div.className = "fleet-event";
            div.dataset.type = "status";
            div.innerHTML = `<span class="event-type">status</span> <span class="event-data">${escapeHtml(payload.status || "?")}${payload.error ? ` — ${escapeHtml(payload.error)}` : ""}</span>`;
            events.appendChild(div);
            es.close();
        });
        es.onerror = () => { es.close(); };
        // Close the SSE when the modal closes
        const obs = new MutationObserver(() => {
            if (!document.body.contains(backdrop)) {
                es.close();
                obs.disconnect();
            }
        });
        obs.observe(document.body, { childList: true, subtree: true });
    }

    async function promptAndSpawn(name) {
        const prompt = window.prompt(`Run ${name} with prompt:`);
        if (!prompt || !prompt.trim()) return;
        try {
            await fetch(`/agents/${encodeURIComponent(name)}/run`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: prompt.trim() }),
            });
            refresh();
        } catch (e) {
            // Silent
        }
    }

    // ---- boot ----

    refresh();
    setInterval(refresh, REFRESH_INTERVAL_MS);
})();
