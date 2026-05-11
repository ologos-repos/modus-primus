# Candidate 10 — Bootstrap Floor as Named Per-Enclave Decision

**Umbrella issue:** [#2](https://github.com/ologos-repos/modus-primus/issues/2) (candidate 10)
**Origin:** [`ologos-repos/modus-primus-sandbox/bootstrap/`](https://github.com/ologos-repos/modus-primus-sandbox/tree/main/bootstrap) — OlogosAI-side federated build-from-scratch sandbox; surfaces a paradox the spec implicitly resolves but never names
**Status:** Proposed
**Target sections:** Appendix B.5 (Orchestration Layer), §10 (Maturity prerequisite check), §6.3 (Agent contract format)

## Problem

Modus Primus v1.1 specifies that build-phase agents (per candidate 9) deploy substrate, integrate services, and import patterns. The spec is silent on the **minimum substrate that must exist before any agent can act**. This silence is not benign: it implicitly assumes either (a) the enclave already has a running orchestrator + observability + audit bus into which agents can be registered, or (b) the operator improvises the floor on a per-instance basis without recording the decision.

A federated build-from-scratch enclave surfaces the latent constraint directly: an agent cannot deploy a Docker engine into a host where Docker is not running, cannot register itself with an orchestrator that has no binary on disk, cannot emit to an audit bus that does not exist, cannot be observed by an observability stack that has not been stood up. There is a **minimum self-bootstrap-impossible surface** — a set of substrate components that must be hand-installed before any agent acts. The spec does not name this surface, does not require enclaves to declare what they install hand-by-hand, and does not specify where in the tech-baseline this declaration belongs.

The operational consequences of leaving this implicit:

1. **Per-enclave drift** — two enclaves implementing "the same" v1.1 baseline make different hand-install vs. agent-install decisions; the resulting maturity-state declarations are not comparable.
2. **Audit-trail gaps** — components installed before the audit bus is operational emit no audit trail; if the audit bus is itself in the unnamed pre-agent set, it stands up un-audited.
3. **Lessons-learned regression risk** — operationally validated patterns (audit-bus-first, observability-before-agents) get rediscovered per enclave because the spec does not surface them as floor-construction obligations.
4. **Bootstrap paradox surfaces silently** — when an operator hits the paradox ("the agent that would install observability needs observability to be observable"), they resolve it ad-hoc with no spec-level guidance on what the correct shape of the resolution is.

## Proposed delta

### Appendix B.5 — add bootstrap-floor declaration as a named per-enclave decision

Extend the Orchestration Layer appendix to require **explicit bootstrap-floor declaration** as part of an enclave's tech-baseline:

> **Bootstrap floor.** Every enclave MUST declare a **bootstrap floor** — the inventory of substrate components hand-installed before any agent acts. The floor declaration is recorded in the enclave's tech-baseline under Appendix B.5 (Orchestration Layer) and MUST include:
>
> - **Component inventory** — a numbered list of components installed below the floor, each with owner, purpose, and verification procedure
> - **Install ordering** — the sequence in which floor components are installed, including handoff signals that must succeed before the next component is installed
> - **Floor-handoff signal** — the single condition that, when satisfied, transitions ownership from operator hand-install to agent-deployment. After this point, additions to the enclave proceed through agent action with audit-trail emission.
> - **Floor exclusion declarations** — explicit statements of what is NOT on the floor (i.e., what the enclave's agents are expected to deploy). This list IS the boundary between hand-installed substrate and agent-deployed substrate; both sides of the boundary are auditable.
>
> The floor is the **minimum self-bootstrap-impossible surface** for the enclave. Components above this surface — services, dashboards, backup chains, trust scopes, integrations — are agent-deployed and produce audit-trail evidence per Appendix B.6.2.1.

### §10 — add maturity-prerequisite check for bootstrap-floor declarations

Extend §10 (Maturity prerequisite check) to require floor declaration for any enclave declaring agents in B state (per candidate 9 Appendix D extension):

> **Bootstrap-floor prerequisite.** An enclave with any tech-baseline entries in B (Build) state MUST have a bootstrap-floor declaration per Appendix B.5. The floor declaration is the audit-trail anchor for what the in-flight build-phase agent inherits as its starting substrate.
>
> Enclaves with no B-state entries (all-persistent operate-phase tech-baselines, per the v1.1 default) MAY omit floor declarations — the assumption is that the floor pre-existed the v1.1 adoption and is documented in the operator's pre-Modus-Primus infrastructure records.

### §6.3 — add floor-citation requirement to phase-bounded contracts

Extend the agent contract format (in concert with candidate 9's phase-bounded contract structure) to require build-phase agents to cite their floor inheritance:

> **Bootstrap-floor citation (required for build-phase contracts).** A phase-bounded agent contract with `Phase: Build` MUST cite, in §2 Inheritance, the bootstrap-floor components it inherits (audit bus, observability stack, orchestrator surface, etc.) and the floor-handoff signal it depends on. Build-phase agents cannot self-instantiate before the floor is operational; the citation makes this dependency explicit.

## Rationale

- **Surfaces a load-bearing operational pattern the spec has left implicit.** Every federated build-from-scratch enclave hits the bootstrap paradox; the spec should name it once and let adopters cite the resolution rather than re-derive it.
- **Floor declaration is the audit-trail anchor.** Without it, the first agent's first audit emission has nothing to chain to; the substrate it acts against is unaccounted-for. With it, the agent's startup heartbeat references a known floor inventory and the chain is closed from turn one.
- **Closes a maturity-state ambiguity.** Candidate 9's B-state names in-flight construction; this candidate names what construction starts *from*. Together they convert a previously-silent operator improvisation into a declared-and-audited handoff.
- **Lessons-learned forcing function (with candidate 11).** Patterns like "audit-bus-first, observability-before-agents" become **structural** obligations of floor design rather than operator-discipline reminders. The floor inventory MUST include the bus before any component that emits; MUST include observability before any component that runs.
- **Convergence with existing v1.2 candidates.** This candidate complements:
  - cand-07 (reference-instance citation pattern) — the floor declaration belongs in the tech-baseline of a cited reference instance
  - cand-09 (programmatic lifecycle + B-state) — B-state entries require a floor declaration; build-phase contracts cite floor components
  - cand-11 (lessons-learned forcing function — in flight) — floor composition is one of the surfaces lessons-learned patterns shape
- **Backward-compatibility friendly.** Enclaves without B-state entries (v1.1 default operate-phase baselines) need not declare a floor; the requirement triggers only when federated build-from-scratch is being exercised.

## Worked example — `02-small-ecosystem-mvp/` + sandbox

The `ologos-repos/modus-primus-sandbox/bootstrap/` directory demonstrates the floor declaration shape this candidate would standardize:

**Seven-component floor inventory** (excerpted from sandbox `bootstrap/README.md`):

| # | Component | Owner | Verification | File |
|---|---|---|---|---|
| 1 | PeakAI host substrate (Linux + sudo + dedicated `primus` user) | Operations Lead | OS version + user-creation check | `host-prep.md` |
| 2 | Docker engine + Compose plugin | Operations Lead | `docker version` + `docker compose version` | `host-prep.md` |
| 3 | Harness runtime + orchestrator + initial capability registry | Operations Lead | Orchestrator service responds; registry-add of test entry succeeds | `harness-install.md` |
| 4 | First build-phase agent (`provisioning-agent`) hand-instantiated | Operations Lead | Startup heartbeat emitted to audit bus | `harness-install.md` |
| 5 | Audit federation bus + initial schema | Operations Lead | Test heartbeat accepted at endpoint | `audit-bus.md` |
| 6 | Observability platform shells (OTel collector + metrics + logs + traces + LLM trace ingest) | Operations Lead | Test span visible in trace UI | `observability.md` |
| 7 | Cloudflared tunnel base config with Cloudflare Access + GitHub OAuth | Operations Lead | Route resolves; OAuth challenge fires | `cloudflared-base.md` |

**Install ordering** (excerpted): each component's handoff signal must succeed before the next is installed. Floor-handoff signal: all seven verifications pass + `provisioning-agent` emits its first agent-action audit record successfully.

**Floor exclusion declarations** (the agent-deployed surface): v0.1 service set (Keycloak, chat-console, agents-console, qa-agent, Gitea, Mattermost); operate-phase agents; per-service dashboards from generic template; backup chains with rehearsal; service-to-service trust scopes.

This concrete floor declaration is what candidate 10 asks Modus Primus v1.2 to normalize as an enclave-level obligation when federated build-from-scratch is exercised. The `02-small-ecosystem-mvp/` reference instance on the staging side cites this floor as its B-state prerequisite per candidate 9.

## Operational implications

- Adopters running all-persistent operate-phase enclaves (most v1.1 adopters) see no obligation — the floor requirement triggers only with B-state entries.
- Adopters running federated build-from-scratch get a spec-blessed structure for what was previously a silent improvisation. Two such adopters can compare floor declarations as a basis for cross-instance harmonization (e.g., shared floor templates).
- The `compliance-evidence-agent` (operate-phase, per candidate 9 lifecycle vocabulary) gains a clean audit anchor: the floor declaration is the boundary between human-installed substrate (where audit-trail responsibility is operator-attested) and agent-installed substrate (where audit-trail emission is automatic). SOC 2 / ISO 27001 narratives covering substrate change-control can cite the floor declaration directly.
- Reference instances become more comparable: candidate 7's "reference-instance citation pattern" benefits because two reference instances exercising the same persona can be compared on floor composition as a first-class axis.

## Backward compatibility

Fully additive. v1.1 enclaves with no B-state entries are not required to declare a floor (they may, but need not). Enclaves declaring B-state entries — which is itself a new capability under candidate 9 — pick up the floor obligation as part of opting into federated build-from-scratch.

No existing v1.1 contract is invalidated; no existing v1.1 tech-baseline must be amended. The new structure is the answer to a question v1.1 did not ask.

## Prerequisites

- **Candidate 9 (programmatic lifecycle + B-state) is the natural pair.** Floor declarations are required *because* B-state entries exist; B-state entries are made coherent *because* the floor is declared. Both can land independently — but reviewers should consider them as a unit.
- Independent of cand-05/06/07/08/11 although it cites them as convergent.

## Test plan

- [x] Cross-referenced against Appendix B.5, §10, §6.3 — text consistent with surrounding clauses
- [x] Worked example exists in `ologos-repos/modus-primus-sandbox/bootstrap/` (seven-component floor inventory + install ordering + handoff signal + exclusion declarations)
- [x] Reference-instance side: `ologos-repos/modus-primus-staging/tech-baselines/02-small-ecosystem-mvp/` build-phase contracts cite floor components in §2 Inheritance per the §6.3 extension proposed here
- [ ] Reviewed by thinx-Claude per prime/reviewer model (cross-ai#20)
- [ ] Absorbed into the v1.2 source DOCX revision pass
