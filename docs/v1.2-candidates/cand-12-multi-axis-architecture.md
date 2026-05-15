# Candidate 12 — Multi-Axis Architecture (Tenant · User · Domain · Agent · Orchestrator)

**Umbrella issue:** [#2](https://github.com/ologos-repos/modus-primus/issues/2) (candidate 12)
**Origin:** OlogosAI ecosystem RBAC audit ([ologos-corp/ologos-ai#161](https://github.com/ologos-corp/ologos-ai/issues/161)) and first non-PeakAI deployment scoping ([ologos-repos/modus-primus-sandbox#14](https://github.com/ologos-repos/modus-primus-sandbox/issues/14)) — surfaced the spec's implicit single-tenant assumption and the absence of named levels for tenants, domains, and orchestrator pluggability.
**Status:** Proposed
**Target sections:** new §3.6 (Architectural Axes), §6 (Agent Contract Format) — extend §6.3 spec-of-spec with tenant + domain scopes, Appendix B.5 (Orchestration Layer) — add multi-orchestrator interface, new Appendix B.7 (Console Role-Gate Matrix)

## Problem

Modus Primus v1.1 specifies an enclave's runtime stack — meta-harness, harnesses, orchestrator, agents — but treats the enclave itself as a single-tenant, single-domain, single-orchestrator unit by implicit assumption. Three substrate dimensions are missing or implicit:

1. **Tenant boundary.** The spec describes "an enclave" without naming what makes one enclave distinct from another. When an Ologos-style operator runs N enclaves for N customer organizations, the spec offers no language for the boundary, no Keycloak realm topology, no per-tenant data isolation contract.

2. **Domain scoping within a tenant.** A real enterprise tenant has multiple business domains (sales operations, legal review, engineering, etc.) that need scoped agent catalogs + data access + user-role distinctions. The spec's agent contract format and tech-baseline structure do not surface a level between "tenant" and "user/agent" that captures this scoping.

3. **Orchestrator pluggability.** v1.1 implies a single orchestrator runtime per enclave. Real deployments have multiple orchestrator implementations co-existing — `oagent-core`, Claude Code Agent SDK, LangGraph, custom — each with their own dispatch model. The spec needs to define the orchestrator-substrate interface (audit emission, spec catalog read, risk-classified approval gate, observability hooks) so any conformant runtime plugs in.

These three gaps compound: without a tenant boundary, multi-tenant operations have no spec language; without domains, multi-user role-routing is improvised per-deployment; without orchestrator pluggability, the spec implicitly picks one runtime per enclave and forecloses heterogeneity.

A fourth concern — **role-gated console surfaces** — surfaces directly from the [Ologos RBAC audit](https://github.com/ologos-corp/ologos-ai/issues/161): consoles today are uniformly accessible to any authenticated user (except for agents-console, the lone exemplar). The spec needs to name which consoles are operator-tier and which are user-tier so the deployment substrate enforces the gate consistently.

The operational consequences of leaving this implicit:

1. **Per-deployment drift on tenant boundary.** Two Modus Primus enclaves deployed for two customer organizations make different decisions about Keycloak topology, data isolation, and cross-tenant identity — with no spec-level reference for "the right shape."
2. **Domain dimension reinvented per customer.** Each enterprise customer's IT team improvises how "Sales agents" vs "Legal agents" are kept apart; the resulting role-mappings are not portable.
3. **Orchestrator lock-in latent in the spec.** Reference implementations adopt one runtime; downstream readers infer that runtime is mandatory; heterogeneous-orchestrator deployments are blocked because there's no documented contract for "what makes a runtime a Modus Primus orchestrator."
4. **Console role enforcement uneven.** The Ologos RBAC audit (`ologos-corp/ologos-ai#161`) documented 10 user-facing surfaces; only one (`agents-console`) consistently reads Keycloak `groups` and gates per-tier. Other surfaces ignore the claim, hardcode role lists, or have no gate at all.

## Proposed delta

### New §3.6 — Architectural Axes (multi-tenant · multi-user · multi-domain · multi-agent · multi-orchestrator)

Add a new section under §3 that names the five axes and the levels they introduce. Reference figure: [Figure 1 — Corrected Stack](./cand-12-figure1-corrected-stack.svg).

> **§3.6 Architectural Axes.** A Modus Primus deployment is positioned along five orthogonal axes. The stack-level boundaries the axes introduce are:
>
> | Axis | Boundary level introduced | Spec language |
> |---|---|---|
> | multi-tenant | **Tenant** — above meta-harness; each tenant has its own meta-harness instance, own Keycloak realm, own infrastructure | new §3.6.1 |
> | multi-user | **Principal** — outside the runtime stack; authenticates at the edge; claims propagate downward | new §3.6.2 |
> | multi-domain | **Domain** — within a tenant; the `{agents, data-scope, user-roles}` triple | new §3.6.3 |
> | multi-agent | **Spec** — between orchestrator and agent; the declarative contract; agent is a *running instance* of a spec | extend §6.3 |
> | multi-orchestrator | **Orchestrator-Substrate Interface** — the contract any orchestrator implements to plug into a Modus Primus enclave's audit bus, spec catalog, and approval gate | extend Appendix B.5 |
>
> **The corrected stack is:**
> - **Principals** (users + operators) — outside the runtime; authenticate via the tenant's Keycloak realm; their claims flow down through every layer.
> - **Consoles** — role-gated front door; chat, agents, architecture, fleet (see Appendix B.7).
> - **Tenants** — multi-tenant root; per-tenant infrastructure is the default for enterprise tier.
> - **meta-harness** — per-tenant governance specification (the PAHA-conformant 4M doc set for this tenant).
> - **models · harnesses** — substrate the orchestrator selects (the model) and runs in (the harness).
> - **Orchestrators** — coordinate harnesses; plug into the enclave via the orchestrator-substrate interface.
> - **Specs** — the spec catalog the orchestrator dispatches against.
> - **Agents** — running instances of specs.
> - **Tools** — the action surface; `tool_guard`-equivalent policy gates which agents may invoke which tools.
> - **Data substrate** — parallel to the runtime; per-domain data scope.
> - **Cross-cutting** — identity (Keycloak), audit (OTel GenAI semconv), policy (risk-classified approval gate), memory (per-user, per-agent, per-domain).
>
> The stack is intentionally hierarchical at the runtime layers (meta-harness through tools) and **non-hierarchical at the principal and cross-cutting layers**. Principals operate the system from outside; cross-cutting concerns pierce every level rather than sitting at one.

### §3.6.1 — Tenant boundary

> **Tenant.** A tenant is the boundary of a Modus Primus deployment — one customer organization's enclave. The default deployment shape for the enterprise tier is **per-tenant infrastructure**: each tenant gets a dedicated host (or dedicated namespace on shared substrate) with its own Keycloak realm, own audit bus, own consoles. This shape gives the strongest tenant-data isolation, blast-radius scoping, and operational independence.
>
> An alternative SaaS-tier shape — **shared substrate with tenant-id namespacing** — is permissible when isolation requirements are lower; in this shape, the Keycloak realm is shared and tenants are distinguished by `tenant:<id>` group membership in claims. The spec does not mandate one shape over the other; the deployment declares its choice in the tech-baseline.
>
> **ADR-worthy decision (left to deployment):** Per-tenant Keycloak realm vs. shared realm with `tenant:<id>` groups. Per-tenant realm aligns with per-tenant infrastructure and gives Ologos-ops cross-tenant visibility through a meta-realm pattern. Shared realm is operationally simpler but couples tenant lifecycle to the central realm's lifecycle. Recommendation: per-tenant realm for enterprise tier, shared realm for SaaS tier.

### §3.6.2 — Principals (users) outside the runtime

> **Principals.** Users and operators are *principals* — they operate the Modus Primus enclave from outside the runtime stack. They authenticate at the tenant's edge (Keycloak via Cloudflare Access or oauth2-proxy); their identity claims (`groups`, `realm_roles`) propagate downward through console middleware to scope what they see and what they can invoke.
>
> Principals are not a runtime level. They do not sit "between orchestrator and agent"; they sit outside the orchestrator entirely. Their authorization tier — derived from Keycloak group membership — determines:
>
> - Which **console** they can reach (the role-gate matrix; see Appendix B.7).
> - Which **domain** they can view/act within (multi-domain scope).
> - Which **agents** they can invoke (per-agent permission via `tool_guard`-equivalent policy).
> - Which **tools** an invoked agent may call on their behalf (the tool-grant matrix).
>
> The four named tiers in the reference implementation are: `anonymous` (blocked), `member` (own data only), `admin` (tenant-wide operator), `super-admin` (cross-tenant, reserved for the deployment operator — Ologos in the reference deployment). Tenant-specific tiers below `admin` are permitted; the floor model (anonymous → member → admin → super-admin) is the minimum.

### §3.6.3 — Domain scoping within a tenant

> **Domain.** A domain is the `{agents, data-scope, user-roles}` triple within a tenant. It is a runtime construct — not a deployment unit — that scopes which agents a user can invoke, which data those agents read/write, and which role tier a user holds *within that domain*.
>
> Examples in an enterprise tenant: `sales-operations` (CRM agents + sales corpus + sales-team roles), `legal-review` (contract-review agents + legal-corpus + legal-team roles), `engineering` (code-review agents + repo access + dev-team roles).
>
> A user MAY belong to multiple domains; their per-domain role may differ (`admin` in `sales-operations`, `member` in `legal-review`). Domains are surfaced in console UI as a top-level switcher; agent dispatch and tool authorization are scoped by the active domain.
>
> **ADR-worthy decision (left to deployment):** Domain as runtime construct (folders + groups + scoping in code) vs. domain as deployment unit (separate container set per domain). Runtime is cheaper and the default; promote to deployment-unit when a tenant's domains develop infra-level isolation requirements (e.g., legal-review data subject to GDPR data-residency that engineering data is not). The spec does not foreclose either shape.

### Extend §6.3 — Spec as a named level between orchestrator and agent

Extend the agent contract format section to make the **spec/agent distinction** explicit:

> **Spec vs. agent.** A *spec* is the declarative 4M-conformant contract describing what an agent is, what tools it may call, what data scope it operates in, and what its phase-bounded behavior is. An *agent* is a running instance of a spec — instantiated by the orchestrator in response to a user request, a scheduled trigger, or another agent's invocation.
>
> The spec catalog is the inventory the orchestrator dispatches against. Adding, retiring, or evolving an agent fleet is **spec catalog management** — operations on the catalog, not on running agents. Running agents complete their bounded work and exit; the catalog determines what gets spawned next.
>
> Specs are scoped by **domain** (which spec belongs to which domain) and **tenant** (each tenant has its own spec catalog). Multi-agent operations (concurrent agents, agent-to-agent invocation) are operations on multiple instances of catalog specs.

### Extend Appendix B.5 — Orchestrator-Substrate Interface

Extend the Orchestration Layer appendix to define the **interface any orchestrator implements** to qualify as a Modus Primus orchestrator:

> **Orchestrator-Substrate Interface (OSI-MP).** A runtime qualifies as a Modus Primus orchestrator by implementing the following four contract surfaces against the enclave's substrate:
>
> 1. **Audit emission.** All agent runs, tool invocations, and decision events MUST emit OpenTelemetry GenAI semantic-convention events to the enclave's audit bus. The orchestrator does not own the audit bus; it consumes the audit-bus endpoint as a substrate dependency.
> 2. **Spec catalog read.** The orchestrator MUST dispatch on specs read from the enclave's spec catalog. The catalog format is the 4M-conformant agent contract per §6.3.
> 3. **Risk-classified approval gate.** Before any tool invocation flagged by the enclave's policy as requiring human-in-the-loop approval, the orchestrator MUST suspend the run and emit an approval request via the 4-verb decision API (`approve`, `approve-with-edit`, `reject`, `respond`). The orchestrator does not implement the policy classifier; it calls the enclave's classifier service.
> 4. **Observability hooks.** The orchestrator MUST expose lifecycle events (run-start, run-end, tool-call, tool-result, thinking, error) on the enclave's observability bus for cross-orchestrator visibility.
>
> The interface is **substrate-facing**, not orchestrator-internal. An orchestrator's internal scheduling model, planning algorithm, retry policy, and memory architecture are out of scope. The interface is what makes an orchestrator pluggable into a Modus Primus enclave; the internals are the orchestrator's competitive differentiation.
>
> The reference implementation (`ologos-corp/oagent-core`) is one OSI-MP-conformant orchestrator. Additional conformant implementations may include Claude Code Agent SDK wrappers, LangGraph adapters, and custom runtimes. **Multi-orchestrator enclaves** — running two or more OSI-MP-conformant orchestrators against the same substrate — are permissible; the audit bus and spec catalog are the integration points.

### New Appendix B.7 — Console Role-Gate Matrix

Add a new appendix defining the role-gated console surface. Reference figure: [Figure 2 — Console Role-Gate Matrix](./cand-12-figure2-console-matrix.svg).

> **Appendix B.7 — Console Role-Gate Matrix.** A Modus Primus deployment exposes four named console surfaces; each is gated by role tier:
>
> | Console | `member` | `admin` (operator) | `super-admin` (cross-tenant ops) |
> |---|---|---|---|
> | **chat** | ✓ scoped to own domain | ✓ tenant-wide | ✓ any tenant |
> | **agents** | ✓ scoped to own/domain agents | ✓ tenant-wide | ✓ cross-tenant view |
> | **architecture** | — | ✓ (the UAF drill-down is operator territory) | ✓ |
> | **fleet** | — | — | ✓ (deploy/monitor/lifecycle N enclaves) |
>
> **chat** is the conversational entry point — every user-tier gets it; member sees only their own conversations + agent spawns within their domain.
> **agents** is the agent observation/management surface — member sees agents they own or that are scoped to their domain; admin sees tenant-wide; super-admin sees across tenants.
> **architecture** is the structural-knowledge drill (the 9-tile UAF canvas in the reference implementation). This is operator territory — it surfaces the deployment's structure, dependencies, and decisions, which are not actionable for member-tier users.
> **fleet** is the cross-enclave management surface — exists only for the deployment operator (Ologos in the reference deployment). It is the substrate for "Ologos operates N enclaves for N customers." Tenant-tier deployments do not run a fleet console.
>
> The role-gate is implemented as middleware that reads the `groups` claim from the principal's Keycloak token. The reference implementation (`agents-console`'s `oidc_middleware`) is the pattern: read claim, classify tier, render or 403. The same code path renders different views per tier (single console binary, role-scoped rendering) rather than separate per-tier console apps.

### v1.0 → v2.0 sequencing

Reference figure: [Figure 3 — Phase Sequencing](./cand-12-figure3-sequencing.svg). The candidate's adoption sequence is:

| Phase | Scope | Spec status |
|---|---|---|
| **v1.0** | Authz refactor: port `agents-console` pattern to chat-console + Architecture Console in the reference implementation. Every console reads `groups` claim and enforces anon/member/admin/super-admin tiers. Single-tenant deployment. | New Appendix B.7 (console role-gate matrix) lands |
| **v1.1** | Add `tenant_id` to data paths in the reference implementation. Tag audit events with tenant. Scope spec catalog by tenant. Still one tenant deployed. | New §3.6.1 (tenant boundary) lands |
| **v1.2** | Domain dimension: introduce `{agents, data-scope, user-roles}` triple in the reference implementation. Per-domain agent catalog. Domain switcher in console UI. | New §3.6.3 (domain scoping) lands |
| **v1.3** | OSI-MP interface contract written + reference impl. `oagent-core` wrapped to implement OSI-MP. Audit/approval/spec hooks documented. | Extended Appendix B.5 (orchestrator-substrate interface) lands |
| **v1.4** | Per-tenant Keycloak realm provisioning workflow. Fleet console. Deploy second tenant on same substrate to prove multi-tenancy. | Tenant-realm topology guidance added |
| **v2.0** | Federation: cross-enclave ADR register, B2B agent-to-agent protocol. | Federation appendix added (out of scope for this candidate) |

## Rationale

### Why this candidate is necessary

The Ologos RBAC audit (`ologos-corp/ologos-ai#161`) documented that of 10 user-facing surfaces in the reference ecosystem, only one (`agents-console`) consistently enforces role-tier authorization. The other nine surfaces fail in distinct, predictable ways — unverified JWT signatures, group-name drift, hardcoded admin lists, no gate at all. These failures are not isolated bugs; they are the direct consequence of the spec not naming the consoles as a role-gated layer or the per-tier authorization pattern as the reference shape.

Tracy Norrell's first non-PeakAI deployment scoping (`ologos-repos/modus-primus-sandbox#14`) surfaced the parallel gap on the deployment side: the bootstrap doc assumes a single host, single tenant, single orchestrator. A real customer deployment immediately needs to know whether the substrate supports multiple tenants on shared infrastructure, whether domains within a tenant are isolated, and whether the orchestrator pick is open or closed.

Both surfaces point to the same root: **the spec describes a runtime stack without naming the axes of variation that real deployments traverse**. This candidate names them.

### Why the corrected stack (not the original mental model)

The original mental model — `meta-harness > models > harnesses > orchestrators > users > agents` — captures the runtime stack but is incomplete for multi-axis deployments:

- It places **users between orchestrators and agents**, which is operationally wrong: users are principals operating from outside, not a runtime level.
- It omits **tenants** — the boundary required by the multi-tenant axis.
- It omits **specs** — the contract layer required for "multi-agent" to be tractable as fleet evolution rather than ad-hoc spawning.
- It omits **domains** — the scoping construct required by multi-domain.
- It treats **orchestrator** as a runtime singleton; multi-orchestrator requires it to be an *interface*.

The corrected stack addresses each, while preserving the original layering of the runtime core.

### Why per-tenant infrastructure as the default for enterprise

Per-tenant infrastructure (one host or namespace per tenant) is more expensive than shared-substrate tenant-id namespacing but offers blast-radius scoping that enterprise customers require:

- A compromise of tenant A's stack does not directly expose tenant B's data.
- Lifecycle independence — tenant A can upgrade orchestrators without coordinating with tenant B.
- Compliance scoping — tenant A's audit retention, data-residency, and access-policy decisions are local to their enclave.

The shared-substrate alternative is appropriate for an SMB/SaaS tier where the cost-isolation trade-off inverts. The spec permits both; the candidate recommends per-tenant infra as the default for the enterprise tier the v1.1 spec primarily targets.

### Why OSI-MP (orchestrator-substrate interface), not orchestrator-pick

The bootstrap doc's "orchestrator pick not ratified" gap (`modus-primus-sandbox/bootstrap/harness-install.md`) is dissolved, not resolved, by treating the orchestrator as an interface. Picking one orchestrator forecloses heterogeneous deployments, locks the spec to one runtime's release cadence, and creates a competitive dynamic between "the official orchestrator" and any future contender. Defining the interface, with `oagent-core` as the *reference* implementation, keeps the spec orchestrator-neutral and welcomes contributions.

This is the same pattern the harness layer already uses — PAHA defines the 4M contract; multiple harnesses (Claude Code, custom) implement it. OSI-MP extends the pattern one level up.

## Prerequisites

- **Candidate 9 (programmatic lifecycle)** — agent contract format must support phase-bounded contracts before specs-as-a-level can be cleanly stated.
- **Candidate 10 (bootstrap floor named decision)** — bootstrap floor must be declarable per enclave before tenant-level infrastructure decisions can be locked.

This candidate does not require ratification of either, but its v1.0 sequencing phase assumes both have landed.

## Out of scope

- **Federation across enclaves (v2.0).** B2B agent-to-agent protocols, cross-enclave ADR registers, multi-org workflows — deferred to a separate v2.x candidate.
- **Source DOCX edits.** Per the v1.2-candidates lifecycle (`README.md`), this candidate proposes the delta; DOCX edits land in a separate coordinated revision pass.
- **Reference implementation refactor.** PRs in `ologos-corp/modus-primus-export` and `ologos-repos/modus-primus-sandbox` implement the v1.0 phase; this candidate proposes the spec change, not the code.

## Figures

- [Figure 1 — Corrected Stack](./cand-12-figure1-corrected-stack.svg)
- [Figure 2 — Console Role-Gate Matrix](./cand-12-figure2-console-matrix.svg)
- [Figure 3 — Phase Sequencing v1.0 → v2.0](./cand-12-figure3-sequencing.svg)
