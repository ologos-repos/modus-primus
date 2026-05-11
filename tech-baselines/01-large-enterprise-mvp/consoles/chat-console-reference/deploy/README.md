# Deployment — Chat Console Reference

Deployment artifacts for the chat console reference kit. The reference uses a systemd-user service pattern; adopters operating under different process supervisors (systemd-system, Docker / Podman, Kubernetes, Nomad) can substitute equivalent invocations.

## Files

| File | Purpose |
|---|---|
| `console.service.template` | systemd user-unit template. Copy to `~/.config/systemd/user/console.service` and customize `[ENTERPRISE:]` markers |
| `.env.example` | Environment variable template. Copy to `.env` (one level up) and populate |
| `bin/install-service.sh` | Install + enable the systemd user service. Idempotent |
| `bin/run.sh` | Dev runner — runs the console in the foreground, loads `.env` if present |

## First-time deployment

1. **Populate `.env`** (in the parent directory, alongside `src/`):
   ```bash
   cp deploy/.env.example .env
   $EDITOR .env  # resolve [ENTERPRISE:] markers
   ```

2. **Install the systemd unit** (or substitute your supervisor):
   ```bash
   deploy/bin/install-service.sh
   ```
   Idempotent — re-running picks up template changes. Validates that `.env` exists before installing.

3. **Verify health endpoint**:
   ```bash
   curl -sf http://127.0.0.1:8080/healthz
   ```

## Adopter customization

Three layers of `[ENTERPRISE:]` markers to resolve:

### Process supervisor

The reference uses systemd-user services because it suits single-host enterprise deployments. Production deployments may use:

- systemd-system (multi-tenant hosts)
- Docker / Podman (containerized; `Dockerfile` is the adopter's to add)
- Kubernetes / Nomad (orchestrated; `Deployment` / `Service` manifests are the adopter's to add)
- Cloud-managed PaaS surfaces (`[ENTERPRISE: app platform — e.g. AWS App Runner, GCP Cloud Run, Azure Container Apps]`)

The console itself is a stateless Python app; choice of supervisor is procurement, not architecture.

### Environment variables

All values in `.env.example` are `[ENTERPRISE:]` markers. Real deployments resolve them per the adopter's environment. The console fails closed on missing required vars; check console startup logs.

### Logging and observability

The reference service emits to systemd journal. Adopters operating observability platforms typically substitute structured logging output to:

- `[ENTERPRISE: observability platform log ingest]` (Datadog, Splunk, Grafana Loki, etc.)
- `[ENTERPRISE: SIEM]` for CyberOps-relevant events
- `[ENTERPRISE: audit federation bus]` for governance audit events per `mechanisms/tools.md`

The pattern is configuration, not code change. See `src/app.py` logging configuration.

## Network topology

Process-supervisor concerns are local to the deployment host. Network reachability between this console and sibling services (agents console, cognitive substrate, observability platform) is the adopter's responsibility — see `../network/` for the reference patterns.
