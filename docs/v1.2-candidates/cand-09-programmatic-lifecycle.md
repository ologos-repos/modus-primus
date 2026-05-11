# Candidate 9 — Programmatic Lifecycle + B (Build) Maturity State + Phase-Aware Means

**Umbrella issue:** [#2](https://github.com/ologos-repos/modus-primus/issues/2) (candidate 9)
**Origin:** [`ologos-repos/modus-primus-staging/tech-baselines/02-small-ecosystem-mvp/`](https://github.com/ologos-repos/modus-primus-staging/tree/main/tech-baselines/02-small-ecosystem-mvp) — OlogosAI-side second reference instance; surfaces patterns the `01-large-enterprise-mvp/` reference doesn't exercise
**Status:** Proposed
**Target sections:** Appendix B.6.2.1 (Agent lifecycle), Appendix D (Tech baseline maturity legend), Appendix B.3.5 (`means.md`), §6.3 (Agent contract format)

## Problem

The agent lifecycle states in Modus Primus v1.1 B.6.2.1 are observed-state declarations (Active, Suspended, Retired) used as records. The `01-large-enterprise-mvp/` reference instance exercises only the all-persistent case — every agent in the catalog operates indefinitely; no retirement is anticipated at instantiation time. Maturity states in tech-baselines (Appendix D legend: Mature / Partial / Aspirational) describe the *current static state* of an artifact; they don't accommodate *intentionally transitional* states such as "this artifact is being built right now by an in-flight agent."

Two latent assumptions surface when a reference instance exercises **federated build-from-scratch** (agents are the construction crew, not just operators of a pre-built ecosystem):

1. **Agent retirement can be predetermined** — a build-phase agent's lifecycle is finite by design (it retires when its domain is stood up), and that finitude is part of the contract at instantiation time, not an emergent decision.
2. **Maturity states need a transitional category** — entries being actively constructed (B status) are structurally different from entries either complete (M / P) or paper-only (A), and rolling them up as A or P misrepresents the state.

Additionally, `means.md` in a federated build-from-scratch instance has different means scope during the build phase than during steady-state operation — write authority is appropriate while constructing the substrate; read-and-emit-only is appropriate once the substrate exists. The v1.1 `means.md` schema doesn't distinguish phases.

## Proposed delta

### Appendix B.6.2.1 — add predetermined-retirement-criteria + lifecycle-phase

Extend the Agent lifecycle section to formalize **two lifecycle phases** an agent may operate in, and to specify how retirement criteria are declared:

> **Lifecycle phases.** An agent contract MAY declare itself as one of:
>
> - **Persistent** (default; current v1.1 behavior) — the agent operates indefinitely; retirement is operator-initiated and ad-hoc; no predetermined retirement criteria
> - **Phase-bounded** — the agent operates during a named lifecycle phase (e.g., build, migration, calibration) and retires with predetermined criteria declared in §5 Lifecycle of the contract. Retirement criteria MUST cite (a) the primary completion condition for the phase (e.g., "v0.1 service set deployed + recovery rehearsals complete"), (b) alternative retirement criteria (operator-initiated), and (c) forced-retirement conditions (persistent failure that cannot self-recover)
>
> **Retirement audit-trail transfer.** A phase-bounded agent's retirement MUST include audit-trail transfer to its successor (if named) or to the operate-phase ownership role (per `§9.5` Agent contract review). Retention obligations survive retirement.

### Appendix D — add B (Build) maturity state to the legend

Add a fourth maturity state to the existing M / P / A legend:

> **B — Build.** Artifact slot is named in the tech baseline and **being actively constructed by an in-flight agent in the current bootstrap cycle**. B-state entries are transitional; the build-phase agent owning the slot drives the transition to M / P / A as the construction proceeds. The B state retires from the legend when the build phase retires (per Appendix B.6.2.1 phase-bounded lifecycle).
>
> Tech baselines that do not exercise federated build-from-scratch (most v1.1 baselines) will not have B-state entries. Tech baselines for instances under bootstrap construction may have most or all entries in B state during the construction window.

### Appendix B.3.5 — add phase-aware means declaration

Extend `means.md` schema to permit phase-aware means scoping:

> **Phase-aware means declarations.** A `means.md` MAY structure its capability inventory (B.3.5.1) and workflow capabilities (B.3.5.2) **per lifecycle phase** when the enclave's agent catalog includes phase-bounded agents. Format:
>
> ```
> ## B.3.5.1 Capability inventory
>
> ### Build-phase elections
>
> (capabilities elected only while build-phase agents are active; retire when the
> phase retires)
>
> - ...
>
> ### Operate-phase elections
>
> (capabilities elected for steady-state operation)
>
> - ...
> ```
>
> When phase-aware structure is used, an agent contract's §2 Inheritance — Means authorization MUST cite the phase from which the agent's means scope is drawn.

### §6.3 — add lifecycle-phase declaration to agent contract format

Extend the Agent contract format guidance to require lifecycle-phase declaration in §5 Lifecycle:

> **Lifecycle-phase declaration (required for phase-bounded contracts).** Contracts declared as phase-bounded MUST include:
>
> - A `Phase:` header naming the phase (e.g., `Build`, `Migration`, `Calibration`)
> - Predetermined retirement criteria in §5 (primary completion condition + alternative + forced-retirement)
> - Audit-trail-transfer obligations in §5 (named successor or operate-phase ownership)

## Rationale

- **Surfaces a real spec contribution.** `01-large-enterprise-mvp/` has 10 all-persistent agents; `02-small-ecosystem-mvp/` has 3 build-phase + 12 operate-phase = 15 agents with predetermined retirement for the build-phase three. The phase-bounded pattern is operationally exercised and produces value (the build-phase agents are *necessary* for federated build-from-scratch) but cannot be expressed in v1.1 vocabulary.
- **Means-scope phase-awareness avoids "always-permissive" workarounds.** Without phase-aware means, a build-phase agent needing write authority during construction either gets that authority *permanently* in `means.md` (overbroad), or gets it via informal escalation (un-auditable). Phase-aware means is the correct shape.
- **B-state in Appendix D is small but load-bearing.** Without it, a tech baseline under bootstrap construction is forced to misrepresent every transitional entry as Aspirational (paper-only) or Partial (incomplete). B-state surfaces the in-flight nature explicitly — auditable, queryable, transitions predictable when the build phase retires.
- **Convergence with existing v1.2 candidates.** This candidate complements:
  - cand-03 (means-election retirement) — phase retirement is the mechanism-retirement analog at the agent level
  - cand-05 (catalog discipline as first-class WBS concern) — predetermined retirement criteria need catalog-discipline gating
  - cand-07 (reference-instance citation pattern) — the `02-small-ecosystem-mvp/` reference instance exercises this candidate

## Worked example — `02-small-ecosystem-mvp/`

The `02-small-ecosystem-mvp/` reference instance demonstrates all four extensions of this candidate:

- **B.6.2.1 phase-bounded contracts:** `agents/_build/provisioning-agent.md`, `integration-agent.md`, `migration-agent.md` (3 build-phase contracts with predetermined retirement criteria)
- **Appendix D B-state:** `tech-baseline.md` declares all entries in B state during bootstrap; transition tracked per build-phase agent
- **Phase-aware means:** `meta-harness/means.md` (skeleton in v0.1; populated under this candidate's structure)
- **§6.3 lifecycle-phase header:** each build-phase contract begins with `**Phase:** Build (retires with audit trail after ...)` header

## Operational implications

- Adopters operating with all-persistent agents (most v1.1 adopters) see no change — the new structures are optional and apply only when phase-bounded contracts are declared
- Adopters operating federated build-from-scratch get a first-class vocabulary for the lifecycle patterns they exercise
- `compliance-evidence-agent` (operate-phase) gains a new audit category — predetermined-retirement-with-audit-trail-transfer — that maps cleanly to SOC 2 / ISO 27001 access-revocation controls

## Backward compatibility

Fully additive. v1.1 contracts are valid v1.2 contracts (all are implicitly Persistent phase). Adopters wishing to express phase-bounded patterns get the new vocabulary; adopters not exercising it ignore it.

## Prerequisites

None. Independent of cand-05/06/07/08/10/11 although it cites them as convergent.

## Test plan

- [x] Cross-referenced against Appendix B.6.2.1, Appendix D, Appendix B.3.5, §6.3 — text consistent with surrounding clauses
- [x] Worked example exists in `ologos-repos/modus-primus-staging/tech-baselines/02-small-ecosystem-mvp/` (3 phase-bounded contracts + B-state tech-baseline + phase-aware means skeleton)
- [ ] Reviewed by thinx-Claude per prime/reviewer model (cross-ai#20)
- [ ] Absorbed into the v1.2 source DOCX revision pass
