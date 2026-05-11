# chat console

The chat-console control surface — a platform-independent, remote-accessible (Tailscale + iPhone PWA) web app that hosts model interaction *and* exposes harness state and tooling around it.

Tracker: [chat-console#15](https://github.com/[ENTERPRISE: maintainer id]/chat-console/issues/15). Project home: [`missions/projects/console.md`](../missions/projects/console.md).

## Run it

Local dev:

```bash
cd console
cp .env.example .env  # edit if needed
bin/run.sh
```

As a systemd user service (recommended on workstation):

```bash
bin/install-service.sh
```

Reach: `http://localhost:8080/` (local) or `http://[ENTERPRISE: workstation host address]:8080/` (Tailscale).

Manage:

```bash
systemctl --user status console
systemctl --user restart console
journalctl --user -u console -f
```

## Architecture

Self-contained — clone the folder + `pip install -r requirements.txt` + set env + run = working chat. Harness-aware features (sidebar, slash commands) bind to a chat-console checkout via `CHAT_CONSOLE_WORKSPACE`.

```
console/
├── app.py                    # aiohttp spine; routes; static serving
├── turns.py                  # per-turn buffer (server-authoritative streaming)
├── sessions.py               # SessionRegistry — context-usage tracking + advice
├── providers/                # pluggable LLM (Claude CLI; OpenAI-compat coming Phase 4)
├── harness/                  # live chat-console state (wraps session-start.py)
├── web/                      # frontend (earth-tone, mobile-responsive, PWA)
├── tests/                    # pytest + pytest-asyncio
├── bin/run.sh                # dev runner
├── bin/install-service.sh    # idempotent systemd-user-service install
├── console.service.template  # systemd unit
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

## Routes

| Path | Method | Purpose |
|---|---|---|
| `/` | GET | Index (HTML shell) |
| `/static/*` | GET | CSS, JS, manifest, sw, avatar |
| `/sw.js` | GET | Service worker (root scope) |
| `/healthz` | GET | Liveness |
| `/turns` | POST | Submit a turn; body `{prompt, session_id?}`; returns `{turn_id, session_id, status}` |
| `/turns/{id}` | GET | Turn state |
| `/turns/{id}/stream?from=N` | GET | SSE stream (resumable from offset N) |
| `/sessions/{id}` | GET | Session stats — context usage, cost, advice |
| `/harness/state?force=true` | GET | Live chat-console readout (cached 30s) |

## Shared memory

Each console conversation is a real [ENTERPRISE: cognitive engine CLI] session (UUID). Same id resumed via `claude --resume <id>` from a terminal sees the full conversation history (and vice versa). cwd defaults to `CHAT_CONSOLE_WORKSPACE` so console + terminal land in the same [ENTERPRISE: cognitive engine CLI] project bucket.

## Tests

```bash
pytest                  # all tests
pytest --cov            # with coverage
pytest tests/test_turns.py -v
```

CI: `.github/workflows/console-tests.yml` runs on push to main and PRs touching `console/**`.
