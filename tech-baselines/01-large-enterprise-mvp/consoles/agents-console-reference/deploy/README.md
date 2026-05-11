# Deployment — Agents Console Reference

Deployment artifacts for the agents console reference kit. The reference uses a systemd-user service pattern; adopters operating under different process supervisors substitute equivalent invocations.

## Files

| File | Purpose |
|---|---|
| `agents.service.template` | systemd user-unit template |
| `.env.example` | Environment variable template — copy to `.env` and populate |

## First-time deployment

1. **Populate `.env`** (in the parent directory, alongside `src/`):
   ```bash
   cp deploy/.env.example .env
   $EDITOR .env  # resolve [ENTERPRISE:] markers
   ```

2. **Install the systemd unit** (or substitute your supervisor):
   ```bash
   cp deploy/agents.service.template ~/.config/systemd/user/agents.service
   # Edit the unit if your deployment path differs
   systemctl --user daemon-reload
   systemctl --user enable agents.service
   systemctl --user start agents.service
   ```

3. **Verify health endpoint**:
   ```bash
   curl -sf http://127.0.0.1:8091/healthz
   ```

## Adopter customization

Three layers of `[ENTERPRISE:]` markers to resolve — same pattern as the chat console kit's `deploy/README.md`:

### Process supervisor

systemd-user is the reference; production deployments often substitute Docker / Podman / Kubernetes / cloud PaaS surfaces. The console is a stateless Python aiohttp app plus an aiosqlite store (replaceable with Postgres for multi-host); supervisor choice is procurement.

### Environment variables

All `.env.example` values are `[ENTERPRISE:]` markers. Console fails closed on missing required vars.

### Persistent state

The reference kit stores agent specs, run history, and audit JSONL on local disk. Production deployments commonly:

- Move the SQLite store to `[ENTERPRISE: managed database — Postgres, MySQL, or cloud-managed equivalent]` for HA
- Stream the audit log to `[ENTERPRISE: audit federation bus]` per the parent baseline's federation schema
- Mirror run-artifact directories to `[ENTERPRISE: artifact registry]` per the parent baseline

These substitutions are configuration, not code change.

## Cognitive engine substrate adapters

The agents console invokes adapters in `src/runtime/` to reach cognitive substrates. Adapters present in the reference:

- Self-hosted inference (Ollama-class)
- Cognitive-engine CLI (substrate-agnostic subprocess pattern)
- Vendor API adapters (OpenAI-class, Anthropic-class, Gemini-class)

Per the parent baseline's Scenario 2 (self-hosted open-weights) framing, the self-hosted adapter is the primary path; cloud adapters are present for adopters running Scenario 1 or hybrid deployments.

Substrate adapter selection per agent spec — see `src/specs/research/ollama-hello.md` and `src/specs/research/openai-hello.md` for the spec-level binding pattern.
