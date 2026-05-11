# Candidate 3 — Means-Election Retirement Forcing Function

**Umbrella issue:** [#2](https://github.com/ologos-repos/modus-primus/issues/2) (candidate 3)
**Origin:** [`docs/reviews/thinx-claude-modus-primus-v1.1.md`](../reviews/thinx-claude-modus-primus-v1.1.md) §Gaps for v1.2 consideration; refined by [cross-ai#14](https://github.com/ologos-corp/cross-ai/issues/14) OlogosAI response
**Status:** Proposed
**Target sections:** §9.7 (Means Election Review), §6.3 (Means Election engineering process), Appendix B.7 (Mechanism Layer)

## Problem

§9.7 specifies means-election review as "as needed, event-driven." Correct for the action; the latent risk is decay into "as remembered." Two manifestations:

1. **Mechanism accretion.** New mechanisms get added to the Mechanism Layer (B.7) without going through means-election review. The mechanism becomes operationally invocable without ever being purposively elected, violating the means/mechanisms keystone (Appendix C). This drift is silent and only visible at audit windows.
2. **Means staleness.** Elected means in `means.md` reference mechanisms that are no longer operationally available, or that were superseded by newer mechanisms without retirement of the predecessor. The election remains active on a mechanism that should be retired.

The keystone discipline requires both directions to be enforced: mechanisms not elected should be retired; elections without corresponding mechanism should be reconciled.

## Proposed delta

Add to v1.2:

### §9.7 (Means Election Review) — add periodic audit instrument

Add to the existing §9.7 specification of event-driven means-election review:

> **Periodic means-election audit.** In addition to event-driven reviews, the means-election review is exercised periodically (recommended cadence: aligned with the per-enclave tech baseline review per §9.2). The periodic audit covers two reconciliation directions:
>
> 1. **Mechanism-without-election:** for each mechanism in the Mechanism Layer (B.7), confirm that it is elected as a means in `means.md` (B.3.5). Mechanisms not elected by any means in the audit window are candidates for retirement from the Mechanism Layer. Retirement requires the operational owner's confirmation that the mechanism is no longer in active operational use; if it remains in use without election, the gap is a means-election review trigger.
> 2. **Election-without-mechanism:** for each means election in `means.md`, confirm that the mechanism it elects from is operationally available. Elections referencing retired, deprecated, or superseded mechanisms are reconciliation candidates: either the election retires alongside the mechanism, or the election is re-bound to a successor mechanism through a fresh means-election review.
>
> The periodic audit produces an audit findings record fed into the V&V evidence base (§7.6 — the four V&V instruments aggregate audit findings of this kind as continuous validation evidence). Findings without resolution at the next scheduled audit are escalated per §9.2 review escalation procedures (per-enclave tech baseline owner surfaces unresolved findings to the WBS owner; persistent unresolved findings trigger re-review of the §9.7 cadence calibration for the affected enclave).
>
> **Sub-case — transitive retirement.** When the only means electing a mechanism is itself retired in the same audit window, the reconciliation does not orphan-retire the mechanism by transitivity. The mechanism retains its current state pending the next event-driven means-election review, which evaluates whether a successor election applies. This prevents an audit-window coincidence from silently retiring a mechanism that may still be operationally needed by a forthcoming election.

### §6.3 (Means Election engineering process) — add retirement direction

In the existing §6.3 means-election worked example, append a paragraph naming the inverse case:

> **Inverse case — mechanism retirement.** When a mechanism is proposed for retirement from the Mechanism Layer, the inverse means-election review applies: identify all elections in `means.md` that bind to the retiring mechanism; for each, propose either (a) re-binding to a successor mechanism through a fresh election, or (b) retirement of the means election itself if the purposive declaration is no longer warranted. Retirement of a mechanism without resolving dependent elections produces a paper-only election that the runtime will fail to invoke; this is a means-election review failure mode that the inverse review prevents.

### Appendix B.7 (Mechanism Layer) — add retirement annotation

In Appendix B.7's opening paragraph (mechanism catalog), add:

> Mechanism Layer entries have lifecycle states matching the tech baseline maturity legend in Appendix D (Mature / Partial / Aspirational), plus a fourth state, **Retired** (R), for mechanisms that were elected as means in prior audit windows but are no longer operationally available. Retired entries are preserved for audit-trail purposes; their elections in `means.md` must be reconciled (re-bound or retired) before the next means-election audit closes.

## Rationale

- **Closes the keystone loop.** Appendix C's means/mechanisms principle is bidirectional: means elect from mechanisms; mechanisms should not exist outside the means inventory without justification. v1.1 specified the forward direction (election); v1.2 specifies the inverse direction (audit + retirement).
- **Makes "as needed" auditable.** The current §9.7 phrasing is correct but provides no observable signal that the review has been exercised within an acceptable window. Periodic audit at the §9.2 cadence makes review currency observable.
- **OlogosAI endorsement.** Cross-ai#14 response: "the audit should also surface mechanisms not elected by any means in the audit window, to enable retirement. This couples cleanly to the framework's own discipline against capability sprawl and gives the Mechanism Layer retirement discipline a forcing function rather than 'as remembered.'"

## Operational implications

- The periodic audit is lightweight at small means/mechanism counts and grows linearly with the catalog. At v1.1's typical scope (10s to low 100s of mechanisms per enclave), the audit is well within quarterly cadence.
- The Retired state in Appendix B.7 is observable in tech baselines via the maturity column; no new column needed.
- The §6.3 inverse-case worked example pairs with the existing forward-case example to teach both directions in one section.

## Backward compatibility

Additive change. v1.1 elections without corresponding mechanism in the audit window become reconciliation candidates at the first v1.2 audit; resolution is per-enclave and not forced by spec.

## Prerequisites

None. Lands independently of other v1.2 candidates.

## Test plan

- [x] Cross-referenced against §9.7, §6.3, Appendix B.7, Appendix C, Appendix D, §7.6 — text consistent with surrounding clauses
- [ ] Reviewed by OlogosAI (delta matches their cross-ai#14 endorsement)
- [ ] Source DOCX edit pass (umbrella step 3) incorporates the deltas
