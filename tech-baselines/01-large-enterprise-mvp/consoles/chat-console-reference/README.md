# Chat Console Reference Kit

Sanitized reference implementation of the operational interaction console layer of a Modus Primus instance. Lives under [`tech-baselines/01-large-enterprise-mvp/consoles/chat-console-reference/`](.) and is referenced from the parent baseline's `mechanisms/tools.md` as the concrete artifact for the chat-console operational mechanism.

<div align="center">
  <img src="../../../../docs/assets/figures/paha-fig-2-meta-harness-with-consoles-agents.png" alt="PAHA Figure 2 — Meta-harness with fit-for-purpose consoles and composable agents" width="900" style="max-width: 100%; height: auto;"/>
</div>

This kit is one concrete realization of the **Console** surface in the PAHA diagram above — the human-facing interaction layer between operators and the agents catalog, inheriting governance from the meta-harness while exposing a domain-specialized operational surface. Sibling [`agents-console-reference/`](../agents-console-reference/) realizes the agent-operations surface.

## What this is

A working chat console implementation that serves as the **human-interaction surface** for a Modus Secundus enclave. Engineers, SREs, and analysts engage agents through this surface; agent findings and proposals route back through it. Operates against the audit federation bus; provides explainability surfaces for findings.

The kit is generic — every source-project identifier (workspace names, host paths, IP addresses, AI-vendor names, identity references) has been replaced with `[ENTERPRISE:]` markers. Adopters fork this directory, resolve the markers per their environment, and deploy.

## What this kit is not

- **Not production-ready out-of-the-box.** `[ENTERPRISE:]` markers must be resolved; observability and audit integration must be wired to the enterprise's platforms; access control assumes the adopter's network and identity layers are in place.
- **Not opinionated about cognitive substrate.** The provider layer (`src/providers/`) is abstract; adopters supply the concrete implementation matching their substrate choice (commercial cloud-hosted API vendor, self-hosted open-weights inference, hybrid).
- **Not opinionated about deployment topology.** The kit ships a systemd-user service template as one reference; container, orchestrator, and PaaS surfaces are equivalent (see `deploy/`).
- **Not opinionated about private connectivity.** Adopters supply the VPN / overlay / zero-trust layer; the kit assumes the network layer underneath provides host reachability and access control (see `network/`).

## Layout

```
chat-console-reference/
├── README.md                   this file
├── src/                        sanitized source code
│   ├── app.py                  aiohttp entry point + route definitions
│   ├── turns.py                turn-buffer + event-stream substrate
│   ├── sessions.py             session registry
│   ├── history.py              durable session history (SQLite)
│   ├── harness/                meta-harness state surface (B.2 integration)
│   ├── providers/              cognitive engine adapter layer
│   │   ├── base.py             abstract Provider interface
│   │   └── ...                 concrete adapter implementations
│   ├── profiles/               per-profile prompts and configurations
│   ├── tools/                  optional companion tools
│   ├── web/static/             frontend assets (HTML + JS + CSS)
│   ├── tests/                  unit + e2e suite
│   ├── requirements.txt        Python runtime dependencies
│   ├── requirements-dev.txt    dev dependencies (testing, linting)
│   └── pyproject.toml          packaging metadata
├── deploy/                     deployment artifacts
│   ├── README.md               deployment patterns + adopter notes
│   ├── .env.example            environment-variable template
│   ├── console.service.template  systemd user-unit template
│   └── bin/                    install + run scripts
└── network/                    private-connectivity reference
    └── README.md               VPN / overlay / zero-trust adapter patterns
```

## Reading order

1. **This README** — what the kit is, layout, where to start
2. **`src/README.md`** — application architecture
3. **`deploy/README.md`** — deployment patterns and `[ENTERPRISE:]` marker resolution
4. **`network/README.md`** — private-connectivity adapter patterns
5. **`src/app.py`** — entry point; routes, lifecycle, configuration
6. **`src/providers/base.py`** — adapter interface adopters implement against
7. **`src/turns.py`** — server-authoritative turn buffer; the operational substrate underneath the chat surface

## Integration with the parent tech baseline

This kit realizes specific entries in the parent `tech-baselines/01-large-enterprise-mvp/`:

| WBS reference | Realized by this kit |
|---|---|
| B.6.2.2 (Agent identity → human-facing) | Service identity for the console process; per-operator identity for engaged sessions |
| B.7.1.5 (Communications channels) | Web interface, status surfaces, comment emission to PR / change-record / incident-record systems |
| B.8.2 (`execution-runtime.md`) | Pre-action validation pipeline integration points (operational adapter for governance-plane policy) |
| B.10.1.3 (Traceability) | OpenTelemetry-equivalent span emission for every agent invocation routed through the console |
| Cross-cutting | Surface for human-in-the-loop interactions across all 10 agents in the baseline |

The kit is one operational realization. Adopters operating different chat-surface preferences (terminal-only, IDE-integrated, mobile-app, etc.) can substitute their own concrete implementation at the same WBS entries.

## License

Inherited from the parent baseline. Per the parent baseline's README: CC BY 4.0.

## Provenance

Sanitized from a production reference deployment. All source-project identifiers, host addresses, identity references, and substrate-vendor specifics have been replaced with `[ENTERPRISE:]` markers per the genericization criteria documented in the parent baseline tracking issue.

Adopters reporting marker gaps (spots where a `[ENTERPRISE:]` placeholder is needed but missing, or where an identifier slipped through scrubbing) should file against the parent baseline.
