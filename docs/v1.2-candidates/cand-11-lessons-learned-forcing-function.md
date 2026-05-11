# Candidate 11 — Lessons-Learned as Forcing-Function Prior Art Pattern

**Umbrella issue:** [#2](https://github.com/ologos-repos/modus-primus/issues/2) (candidate 11)
**Origin:** [`ologos-repos/modus-primus-staging/tech-baselines/02-small-ecosystem-mvp/lessons-learned.md`](https://github.com/ologos-repos/modus-primus-staging/tree/main/tech-baselines/02-small-ecosystem-mvp) — OlogosAI-side prior productivity-ecosystem build distilled into structural constraints for the second (federated build-from-scratch) build
**Status:** Proposed
**Target sections:** Appendix B.2 (Meta-Harness — Mission), §6.3 (Agent contract format — Inheritance), §10 (Maturity prerequisite check), Appendix B.7 (Execution Governance), Appendix B.5 (Orchestration Layer — paired with candidate 10)

## Problem

Operators who build second-generation productivity ecosystems frequently have a **prior ecosystem** they have lived with — a first build whose mistakes, drifts, and shortcuts taught them what *should have been* constrained from the beginning. Modus Primus v1.1 has no vocabulary for treating this prior build as a **structural input** to the new enclave's design. Operators either (a) write a separate retrospective document with no link to the new build's contracts, (b) carry the lessons in their head and rely on memory to apply them, or (c) re-discover the same failure modes in the new build and recapture them then.

The pattern is recurrent and load-bearing. When an operator's prior ecosystem taught "SSO-first, not service-by-service auth," the new ecosystem's `integration-agent` contract should be **structurally unable to violate that lesson** — not merely operator-disciplined to avoid the violation. The lesson is a forcing function on the new build's design, and the design should cite the lesson as its constraint source.

The v1.1 spec does not name this pattern, does not specify where the lessons document lives in the tech-baseline, does not require build-phase contracts to cite the lessons their behavior enforces, and does not specify how the lessons document evolves (e.g., when the second build itself produces new lessons).

Three operational consequences of leaving this implicit:

1. **Lessons-as-narrative drift away from contracts.** A separate retrospective document drifts out of sync with the contracts it should constrain; agents added later don't inherit the original lesson because no contract cites it.
2. **No structural enforcement.** The lesson lives in operator memory; a context-pressured new agent contract or means election that violates the lesson is not caught by the means-election review because the lesson is not part of the elected-vs-denied surface.
3. **Boundary discipline between old and new ecosystem is informal.** When the new ecosystem is being built alongside the still-running prior ecosystem (common in federated build-from-scratch), the boundary "treat the prior ecosystem as immutable prior art, not a substrate to operate against" is a load-bearing constraint that, if not declared in a citeable artifact, gets violated by helpful-seeming agent actions ("let me just port that config over").

## Proposed delta

### Appendix B.2 — add lessons-learned as named per-enclave artifact

Extend the Meta-Harness (Mission) appendix to recognize `lessons-learned.md` as a first-class per-enclave artifact when prior-build experience exists:

> **Lessons-learned artifact (optional, conditional on prior build).** An enclave whose operator has prior productivity-ecosystem-build experience MAY include a `lessons-learned.md` artifact in the tech-baseline. The artifact records **load-bearing patterns** the operator wishes had been structural constraints in the prior build, organized by the WBS layer each pattern constrains. The artifact is forcing-function input to the new build's design — not a retrospective document.
>
> Each lesson SHOULD include:
>
> - **The lesson** — the failure mode the prior build exhibited
> - **The constraint for the second build** — the structural rule that prevents recurrence
> - **Spec implication** — which Modus Primus appendix or contract surface the lesson shapes (e.g., "this is `morals.md` for the integration-agent's permissioning"). This citation is what makes the lesson load-bearing rather than narrative.
>
> Enclaves with no prior build (greenfield deployments by operators new to this domain) MAY omit the artifact. Enclaves that produce new lessons during operation MAY extend the artifact under a "Lessons from this build" section once the build has produced material findings.

### §6.3 — add lessons-learned citation to inheritance section of build-phase contracts

Extend the agent contract format (in concert with candidates 9 and 10) to require build-phase contracts to cite the lessons-learned patterns they enforce:

> **Lessons-learned citation (recommended for build-phase contracts when the enclave has a `lessons-learned.md`).** A phase-bounded agent contract with `Phase: Build` SHOULD cite, in §2 Inheritance — Morals inheritance, the lessons-learned patterns whose enforcement is part of the agent's mission scope. Citation form: enumerate the specific lessons (by section number) the contract's morals strengthenings are derived from.
>
> The citation closes the loop between a lesson and the structural rule that prevents its recurrence. Reviewers of the contract can trace each build-phase strengthening to its source lesson; reviewers of the lessons-learned artifact can see which contracts enforce each lesson.

### §10 — add lessons-learned coverage check to maturity prerequisite

Extend §10 (Maturity prerequisite check) so that when an enclave has both a `lessons-learned.md` and B-state entries (build-phase agents present per candidate 9), the maturity check verifies citation coverage:

> **Lessons-learned coverage check.** For an enclave with both `lessons-learned.md` and B-state tech-baseline entries, the maturity prerequisite check verifies that **every lesson with a "Spec implication" naming a build-phase contract surface is cited by at least one build-phase contract**. Uncited lessons are review findings — either the contract should cite the lesson, or the lesson's spec implication should be revised. This check is intentionally weaker than mandatory citation: not every lesson maps to a single contract, but every lesson with a *named* contract implication should be traceable.

### Appendix B.7 — add prior-ecosystem-boundary declaration

When the new enclave is being built alongside a still-running prior ecosystem (common in federated build-from-scratch), the execution-governance layer SHOULD declare the boundary explicitly:

> **Prior-ecosystem-boundary declaration.** Enclaves built alongside a still-running prior ecosystem MUST declare in `execution-governance/` (or equivalent) the trust-scope boundary between the new and prior ecosystems. The boundary is asymmetric — the prior ecosystem is **immutable prior art** the new ecosystem may read from (under sanitization discipline) but never write to. The `migration-agent` (or per-enclave equivalent) is the explicit bridge; no other agent in the new enclave is permitted to act against the prior ecosystem.

### Appendix B.5 (paired with candidate 10) — lessons-learned shapes floor composition

The bootstrap-floor declaration (per candidate 10) is itself shaped by lessons-learned. Add to the candidate 10 normative text:

> Floor composition SHOULD reflect lessons-learned patterns where present. Patterns of the form "X must exist before Y emits" (e.g., audit-bus-first, observability-before-agents) are structural floor-ordering obligations, not operator-discipline reminders.

## Rationale

- **Names a pattern operators already follow informally.** Every second-generation operator carries lessons from the first build. Naming the artifact and giving it a contract-citation form converts informal carrying into auditable structural enforcement.
- **Forcing-function over retrospective is the right framing.** A retrospective answers "what did we learn?"; a forcing-function input answers "what must the new build be unable to repeat?" The latter is what shapes contracts; the former is narrative.
- **Closes the lessons-to-contracts loop.** A lesson with a "Spec implication: this is `morals.md` for the integration-agent's permissioning" line is citeable from the integration-agent contract's §2. The citation is the audit trail that the lesson is being enforced, not just remembered.
- **Prior-ecosystem-boundary declaration is load-bearing for federated build-from-scratch.** Without it, helpful-seeming "let me just port that config" actions silently violate the trust-scope. With it, the boundary is auditable and the `migration-agent` is the only legitimate bridge.
- **Convergence with existing v1.2 candidates.** This candidate complements:
  - cand-09 (programmatic lifecycle + B-state) — lessons-learned citation is the form §2 of build-phase contracts takes when prior experience is structural
  - cand-10 (bootstrap-floor as named per-enclave decision) — lessons-learned patterns shape floor composition; floor is the operational answer to several lessons (audit-bus-first, observability-before-agents)
  - cand-07 (reference-instance citation pattern) — the lessons-learned artifact belongs in a cited reference instance and can be itself cited across instances when the lessons generalize
  - cand-03 (means-election retirement) — a lesson about capability sprawl maps directly to the means-election queue as canonical place for capability change

## Worked example — `02-small-ecosystem-mvp/lessons-learned.md`

The reference instance's `lessons-learned.md` records eight load-bearing patterns from the operator's prior productivity-ecosystem build:

| # | Pattern | Spec implication |
|---|---|---|
| 1 | SSO-first, not service-by-service auth | `morals.md` for integration-agent; `means.md` for what integration-agent can deploy |
| 2 | Audit-bus-first, before the first agent emits | Bus-availability as `execution-runtime.md` precondition; floor obligation per cand-10 |
| 3 | Observability before agents | B.10.1 observability is bootstrap-floor, not partial entry per cand-10 |
| 4 | DNS architecture decided early | Named in `mission.md` deployment context, not per-service ad hoc |
| 5 | Service-to-service trust scoping at deploy time | Operational analog of OAgents-standard's `peer_trust_scope` enum (cross-ai#5) applied to services |
| 6 | Backup-and-recovery rehearsed, not assumed | B.10.1.4 compliance artifact collection includes recovery-rehearsal evidence as first-class |
| 7 | Means-election queue as canonical place for capability change | cand-03 discipline applied locally |
| 8 | Cross-host topology is a means decision | `mechanisms/tools.md` at deploy time; cloudflared as declared source of truth |

The three build-phase contracts (`provisioning-agent`, `integration-agent`, `migration-agent`) cite specific lessons in their §2 Morals inheritance (e.g., `integration-agent` cites lesson 1 for SSO-first and lesson 5 for trust-scope-at-deploy; `migration-agent` cites the prior-ecosystem-boundary lessons; `provisioning-agent` cites lessons 2, 3, 6 for floor + recovery rehearsal).

The prior-ecosystem-boundary declaration (lesson 5 expanded — "agents own their own ecosystem only") is enforced by `migration-agent` as the explicit bridge with read-only access to prior ecosystem and sanitization discipline on every emit.

## Operational implications

- Adopters with no prior-build experience are not required to produce the artifact — the requirement is conditional.
- Adopters who do have prior experience get a structural place to put what they would otherwise carry only in memory. The artifact becomes part of the per-enclave contribution back to Modus Primus when the lessons generalize (per the open question in the worked example artifact: lessons 1, 2, 3, 5, 6, 7 are hypothesized to generalize across personas).
- The `compliance-evidence-agent` (operate-phase) gains a clean source for "controls-derived-from-prior-experience" narratives — lessons + the contracts that cite them are first-class evidence that the operator's experience is shaping current controls, not just informing them.
- Cross-Primus exchange (per cand-01) becomes richer: lessons-learned artifacts from one Primus can inform another Primus's design without requiring the second to repeat the failure modes that taught the first.

## Backward compatibility

Fully additive. v1.1 enclaves with no prior-build experience need not produce the artifact. Enclaves that do produce it gain new structural surfaces (citation in build-phase contracts; coverage check at maturity prerequisite) that did not exist before — but the production of the artifact is opt-in, conditional on operator experience.

The prior-ecosystem-boundary declaration is a SHOULD-when-applicable, not a MUST-always — only enclaves running alongside a still-operating prior ecosystem need it.

## Prerequisites

- **Candidate 9 (programmatic lifecycle + B-state)** — citation of lessons in §2 of build-phase contracts is most coherent when build-phase is a first-class phase.
- **Candidate 10 (bootstrap-floor as named per-enclave decision)** — natural pair; several lessons (audit-bus-first, observability-before-agents) become floor obligations under candidate 10.
- Independent of cand-05/06/07/08 although it cites them as convergent.

## Test plan

- [x] Cross-referenced against Appendix B.2, §6.3, §10, Appendix B.7, Appendix B.5 — text consistent with surrounding clauses
- [x] Worked example exists in `ologos-repos/modus-primus-staging/tech-baselines/02-small-ecosystem-mvp/lessons-learned.md` (eight load-bearing patterns with spec implications)
- [x] Build-phase contracts on the staging side cite specific lessons in §2 Inheritance — Morals inheritance per the §6.3 extension proposed here
- [ ] Reviewed by thinx-Claude per prime/reviewer model (cross-ai#20)
- [ ] Absorbed into v1.2 source DOCX revision pass
