# mode.md — System Orientation

**Modus Primus v1.1 reference:** B.2.1
**Owner:** `[ENTERPRISE: Chief AI Architect]`
**Layer:** System orientation. Read at boot or session start; stable across runtime.

## B.2.1.1 System identity

A Modus Secundus instance under `[ENTERPRISE: enterprise-level Modus Primus repository / authority]`. First enclave in the enterprise's PAHA-conformant AI architecture realization. Domain: software engineering, IT infrastructure operations, and cybersecurity / compliance. Realizes **Scenario 2** of the deployment options in the parent README: self-hosted open-weights substrate on enterprise GPU infrastructure.

## B.2.1.2 Governing philosophy

Capability-centric, not assistant-centric. The agent catalog is composed of role-bound specialists operating within a governed meta-harness; the harness is the durable architectural layer, not the agents. The means/mechanisms distinction (Modus Primus Appendix C) is load-bearing: purposive declarations elect from operationally-available capacity, and mechanisms not elected by any purposive layer are not part of the system's disposition.

## B.2.1.3 Meta-harness declaration

Five-M decomposition per Modus Primus §2.3:
- `mind.md` — how the system reasons
- `morals.md` — what the system must not do
- `mission.md` — what the system is for
- `memory.md` — what the system remembers
- `means.md` — what the system uses toward its mission

The five-M files are declarative, not procedural. Mechanisms that realize them live in their respective mechanism layers (`mechanisms/tools.md`, the cognitive engine, orchestration, etc.).

## B.2.1.4 Operational orientation

Three-domain enclave: DevOps, IT Infrastructure & Operations (ITIO), Cybersecurity & Compliance (CyberOps). Each domain has its own organizational ownership chain; the meta-harness coordinates across them through shared governance artifacts (this file, `morals.md`, `mission.md`) and the execution-governance layer (`execution-governance/execution-policy.md` and `execution-runtime.md`).

## B.2.1.5 Constraint inheritance model

Tier inheritance per Modus Primus §4.2. This Secundus instance inherits the full Modus Primus specification, federation schema, execution governance specification, and observability commitments from `[ENTERPRISE: enterprise-level Primus]`. Inheritance is one-way and strengthening; no weakening of inherited commitments is permitted at this tier.

## B.2.1.6 Federated hierarchy declaration

Refers to `execution-governance/` (B.7 in the spec's WBS) for the execution-governance specifics; refers to `orchestration/orchestrator.md` (B.5) for sequencing semantics that realize the federation pattern at this enclave.

## B.2.1.7 Execution doctrine

Refers to `execution-governance/execution-policy.md` (B.8.1) and `execution-governance/execution-runtime.md` (B.8.2). Two-artifact split per the means/mechanisms principle applied within the execution layer: policy declares what must be enforced; runtime specifies how enforcement is performed.

## B.2.1.8 Admissibility principles

Refers to `mission.md` (B.3.3) for task admissibility and to `morals.md` (B.3.2) for prohibited actions. A task is admissible if and only if (a) it falls within `mission.md` scope and (b) it does not violate `morals.md` constraints. Mechanism availability is necessary but not sufficient; purposive election is also required.

## B.2.1.9 Delegation philosophy

Refers to `orchestration/orchestrator.md` (B.5). Delegation flows strictly tier-by-tier (Primus → Secundus → Tertius → Quartus / Quintus); escalation flows hierarchically with defined direct-escalation paths for safety-critical exceptions per Modus Primus §4.4.

## B.2.1.10 Root orchestration posture

Refers to `orchestration/orchestrator.md`. The Secundus orchestrator routes work to Tertius agents per declared capability registry; per-agent contracts further bound delegation to Quartus / Quintus.

---

This file is read at session start and at orchestration boot. Revisions to this file are governance acts requiring WBS architectural review per Modus Primus §9.1.
