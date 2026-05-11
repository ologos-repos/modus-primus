# End-to-end smoke tests

Puppeteer-based. Each test boots a real chat-console (Python aiohttp) in
a subprocess on a random port with a deterministic mock generator, then
drives a headless Chromium against the live wire and asserts DOM. No
claude API calls; fast and offline.

## Run

```bash
# Mock-only (default — fast, deterministic, no API calls)
node console/tests/e2e/run.mjs

# Mock + live-stack (--live: dispatches to running agents service +
# Kroki + chat console; small claude API budget per spawn)
node console/tests/e2e/run.mjs --live

# Single test (substring match)
node console/tests/e2e/run.mjs --filter=multi-burst
```

Live tests require `console.service` (port 8080), `agents.service` (8091),
and `kroki.service` running. They're skipped cleanly when those endpoints
aren't reachable. Override URLs via `E2E_CHAT_URL` / `E2E_AGENTS_URL`.

Output is TAP-ish:

```
ok - boot-smoke
ok - synchronous-turn-renders-fully
not ok - multi-burst-text
  # assertion failed: expected 3 text-blocks, got 2
```

Exit code is 0 on all-pass, 1 on any failure.

## Scenarios

| Test | Verifies |
|---|---|
| `boot-smoke` | page loads, sidebar present, send button enabled, no JS errors |
| `synchronous-turn-renders-fully` | text + tool_call + tool_result, body INSIDE matching tool-block (yesterday's duplicate-renderer regression class) |
| `multi-burst-text` | text → tool → text → tool → text renders as 5 alternating blocks in DOM order (the "exploded stream" guard) |
| `markdown-table-rendering` | GFM table tokens render as `<table><thead>...` (post-marked.js) |
| `session-restore-on-reload` | submit a turn, reload, prior turn rendered from history |
| `prompt-queue-during-in-flight` | sending while in-flight queues; on completion, indicator transitions to ready with disposition buttons |

## Files

- `run.mjs` — test runner. Defines scenarios + asserts, exits non-zero on failure.
- `server-fixture.mjs` — boots a chat-console subprocess on a free port with the given inline Python script. Polls /healthz, kills on cleanup.
- `mock-generators.mjs` — inline Python scripts wrapping `build_app(generator=...)` with a specific event sequence per scenario.

## Adding a test

1. Add a mock generator constant to `mock-generators.mjs` if your scenario needs a new event sequence.
2. Add a `test("name", async () => { ... })` block to `run.mjs`.
3. Use `withConsole(SCRIPT, async ({baseUrl}) => withPage(baseUrl, async (page, errors) => { ... assertions ... }))`.
4. Run `node console/tests/e2e/run.mjs --filter=<your-name>` to iterate.

## Live-stack tests

Two scenarios opt-in via `--live`:

| Test | Verifies |
|---|---|
| `live-agents-dispatch-with-output` | POST to agents service, run lands in registry, polls to `done`, JSON record exposes `output` field (regression guard for the empty-preview defect caught at `602422f3`) |
| `live-diagram-render-via-kroki` | POST to chat console's `/render/diagram` proxy, returns `X-Render-Id`, content-addressable GET works for both SVG + PNG |

These run real claude calls (bounded — hello-world prompts are tiny) and exercise the full cross-service path. Skip cleanly with a note when services aren't reachable.
