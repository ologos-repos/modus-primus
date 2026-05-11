# means/agents — agent fleet runtime

The model-transportable agent runtime + console-side fleet UI for agents-console. Spec: [[ENTERPRISE: tracker ref]](https://github.com/[ENTERPRISE: maintainer id]/agents-console/issues/16). Plan: see issue body / approved Phase 1 cut.

> Not to be confused with [`means/agents.md`](../agents.md), which is reference docs for [ENTERPRISE: cognitive engine CLI]'s *subagent types* (Explore, Plan, etc.) — a different, off-the-shelf concept. This directory hosts agents-console's *own* agent runtime, model-agnostic.

## What lives here

```
means/agents/
├── specs/                 # markdown + YAML frontmatter; one agent per file
│   └── <domain>/<name>.md
├── runtime/               # AgentBackend ABC, providers, run lifecycle, daemon
├── web/static/            # frontend assets for the fleet panel (mounted by console)
├── routes.py              # aiohttp routes registered into console/app.py
├── data/                  # SQLite + workspaces (gitignored)
└── tests/                 # pytest
```

## Run / manage

The agent fleet routes are hosted by the existing `console.service` (no separate daemon yet — agent runs are detached subprocesses on demand).

```bash
# View console (which now also surfaces the fleet panel)
http://localhost:8080/

# Direct API
curl -s http://localhost:8080/agents
curl -sX POST http://localhost:8080/agents/<name>/run \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"hello"}'
```

## Tests

```bash
cd means/agents
pytest           # all
pytest --cov     # with coverage
```

CI: `.github/workflows/agents-tests.yml` runs on push to main and PRs touching `means/agents/**`.

## Providers (Phase 6)

Specs declare a model with `<provider>:<model_id>`. Bare values default to `claude` so existing specs keep working. Tools are claude-only — non-claude providers are text-only in this phase.

| Provider | `model:` example | Auth | Notes |
|---|---|---|---|
| `claude` (default) | `claude-sonnet-4-7` or `claude:sonnet` | [ENTERPRISE: cognitive engine CLI] subscription via the `claude` CLI | Subprocess; full tool support |
| `ollama` | `ollama:peakai/qwen3:14b` | none | Hosts named in `data/ollama_hosts.json`; ops can add aliases without code change |
| `openai` | `openai:gpt-4o-mini` | `OPENAI_API_KEY` env | Read from shell env; sourced from `~/.[ENTERPRISE: org identifier]-credentials` |
| `gemini` | `gemini:gemini-2.5-flash` | `GEMINI_API_KEY` env | Same source |

Spawn the same way regardless of provider:

```bash
curl -sX POST http://localhost:8080/agents/ollama-hello/run \
  -H 'Content-Type: application/json' -d '{"prompt":"hi"}'
```

The judge stays claude-CLI based; QA still works for non-claude agents because the judge evaluates recorded events, independent of the agent's runtime backend.

## Services (Phase 7)

Long-lived systemd units appear in the fleet panel as info-only cards alongside on-demand agents. Each service is described by a markdown spec in `specs/services/<name>.md`:

```yaml
---
kind: service
unit: console.service
scope: user            # 'user' (default) or 'system'
purpose: agents-console web control surface
---
Markdown body becomes the description shown in the modal.
```

`kind: service` is the discriminator — files with this key don't appear in `GET /agents` and aren't loadable as `AgentSpec`. The service runtime helper (`runtime/services.py`) shells `systemctl --user show` per render to surface live state, and `journalctl --user -u <unit> -n 30` for the modal's recent-logs view. Both gracefully degrade to "unknown"/empty on subprocess failure (a missing unit on a fresh checkout is normal, not an error).

```bash
curl -s http://localhost:8080/services        # list all + current status
curl -s http://localhost:8080/services/<name> # detail + recent journal
```

Read-only this phase — no start/stop/restart from the UI.

## Workflows (Phase 8)

Linear chains of agent invocations. Each step references an existing agent and supplies a prompt template; the runtime substitutes `{input}` (the workflow's initial input) and `{prev_output}` (the previous step's concatenated text output) at run time, then spawns the agent normally — so QA, approvals, multi-provider, and audit all compose for free.

```yaml
---
kind: workflow
description: Read, summarize, and polish.
steps:
  - id: scan
    agent: file-reader
    prompt: "Read /etc/hostname and tell me what host this is."
  - id: compress
    agent: concise-summary
    prompt: "Compress to under 30 words: {prev_output}"
  - id: polish
    agent: ollama-hello
    prompt: "Rephrase casually: {prev_output}"
---
Body becomes the description shown in the modal.
```

Phase 8 ships **linear chains only** — DAGs / parallel branches / loops are deferred. Templating is plain string replacement (not `str.format`) so unknown placeholders pass through and unbalanced braces in input don't crash the renderer.

```bash
# List workflow specs
curl -s http://localhost:8080/workflows

# Detail with steps
curl -s http://localhost:8080/workflows/<name>

# Run
curl -sX POST http://localhost:8080/workflows/<name>/run \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"initial input"}'

# Recent runs
curl -s http://localhost:8080/workflow-runs

# Detail with linked agent runs
curl -s http://localhost:8080/workflow-runs/<id>
```

Workflow runs spawn their own detached daemon (`workflow_daemon`) which itself spawns each step as a normal child agent run linked back via `parent_workflow_run_id`. The `/runs` listing excludes those children by default to avoid duplication; pass `?include_workflow_steps=1` if you need them.

## Triggers (Phase 9)

Cron-driven scheduler that fires agents or workflows on schedule. The scheduler runs in-process inside `console.service` and ticks every 30 seconds. State persists across restarts.

```yaml
---
kind: trigger
schedule: "*/5 * * * *"          # standard 5-field cron, system-local
target_kind: agent               # 'agent' or 'workflow'
target: hello-world              # name of the target spec
prompt: "morning digest input"   # initial input for the fired run
---
Body becomes the description shown in the modal.
```

**Cron syntax** (v1 minimal): `*` (any), integer literals, and `*/N` step values. Ranges (`1-5`), lists (`1,3,5`), and `@daily` shortcuts are deferred. Expressions are parsed at load time so an invalid spec fails fast.

```bash
# List triggers (with last-fired and next-fire-at)
curl -s http://localhost:8080/triggers

# Detail
curl -s http://localhost:8080/triggers/<name>

# Manual fire (for testing without waiting for the cron edge)
curl -sX POST http://localhost:8080/triggers/<name>/fire
```

Fired runs land in the runs table (or workflow_runs for workflow targets) with `triggered_by: <trigger-name>` so you can tell scheduler-driven runs apart from manual ones. Catch-up policy is **at-most-one** — if the scheduler is down for hours and a 5-minute trigger missed many windows, it fires exactly once on next tick (not 144 times).

## Phases

- **Phase 1**: single-shot agent, fleet card, in-chat reply.
- **Phase 2**: tools allowlist + per-run workspace + tool events.
- **Phase 3**: QA pass via LLMJudge.
- **Phase 4**: per-run approval gates + immutable audit log.
- **Phase 5**: infraops fork (auto-gated, fleet badges).
- **Phase 6**: multi-provider backends (Ollama, OpenAI, Gemini — text-only).
- **Phase 7**: existing services as fleet cards (read-only).
- **Phase 8**: linear workflows (chain of agents with prev_output threading).
- **Phase 9**: cron triggers — in-process scheduler firing agents/workflows on schedule.
- **Phase 9.5+**: webhooks (inbound external triggers). See [#16](https://github.com/[ENTERPRISE: maintainer id]/agents-console/issues/16) for full plan.
