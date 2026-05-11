# Candidate 4 — Runtime-Assurance Commercial-Maturity Survey as Companion Document

**Umbrella issue:** [#2](https://github.com/ologos-repos/modus-primus/issues/2) (candidate 4)
**Origin:** [`docs/reviews/thinx-claude-modus-primus-v1.1.md`](../reviews/thinx-claude-modus-primus-v1.1.md) §Gaps for v1.2 consideration; refined by [cross-ai#14](https://github.com/ologos-corp/cross-ai/issues/14) OlogosAI response
**Status:** Proposed
**Target:** New companion document `docs/runtime-assurance-survey/` (separate from the spec); minor citation update in spec §5.4

## Problem

§5.4 correctly observes that tech baselines may be dominated by aspirational entries in the runtime-assurance layer (B.10.2.1 through B.10.2.4) because commercial products lag. This is true in 2026 and likely to remain true through 2027.

The thinx-Claude review proposed a v1.2 appendix surveying the commercial and open-source state for each runtime-assurance commitment, updated annually. OlogosAI's cross-ai#14 response pushed back on the appendix framing:

> Recommend making it a separate companion document rather than an annual spec appendix — annual updates to a spec appendix trigger a new DOI deposit each year, which is heavy and conflates spec versioning with market-state versioning. A standalone "Runtime Assurance Market Survey 20XX" can churn annually without disturbing spec stability. Pattern: spec cites the latest survey; survey re-cites the spec version it surveys against.

This is the correct shape. The spec describes architectural commitments that change on spec-revision cadence (years); the survey describes the commercial / open-source state that changes on market cadence (months to a year). Conflating them in a single artifact produces unnecessary DOI churn for the spec and unnecessary architectural inertia for the survey.

## Proposed delta

### New companion artifact

Establish `docs/runtime-assurance-survey/` as a separate companion document tracked under this repository:

- **Filename:** `runtime-assurance-survey-YYYY.md` (e.g., `runtime-assurance-survey-2026.md`) per annual edition.
- **DOI:** each annual edition is independently DOI-deposited to Zenodo with a citation back to the surveyed spec version. The survey carries its own version-and-date, distinct from the spec.
- **Scope:** for each runtime-assurance commitment in Modus Primus Appendix B.10.2 (drift detection, mission coherence monitoring, policy deviation detection, explainability surfacing), the survey records: representative commercial products and their current maturity, representative open-source projects, integration patterns observed in production deployments, capability gaps that remain unaddressed by the current market, and update commitments for the following year.
- **Authoring:** community-contributable through PRs against this directory; canonical edition cut annually by Modus Primus authors (or a delegated editor).
- **Lifecycle:** survey editions are immutable post-publication; corrections are issued as errata appended to the published edition, not as in-place edits.

### Minor spec edit (proposed for v1.2)

In Modus Primus §5.4 (Tech Baseline Review Cadence), in the paragraph noting that runtime-assurance entries lag commercial products, append:

> Adopters seeking representative commercial / open-source options for each runtime-assurance commitment may consult the Modus Primus Runtime-Assurance Survey, an annually-revised companion artifact published separately under its own DOI. The spec cites the latest available survey edition; the survey cites the spec version it was prepared against. Adopters should not infer architectural commitments from the survey, and should not infer market state from the spec.

### v1.0 of the survey

A v1.0 of the survey is *not* in scope for this candidate PR. Authoring the survey is a separate effort that this candidate enables; it requires committed editor time and community contribution and should be triggered after the v1.2 spec edit lands.

## Rationale

- **Decouples versioning cadences.** Spec revision (years) and market survey revision (annual) live on independent cycles. Neither imposes its cadence on the other.
- **Avoids DOI thrash.** Spec DOI represents architectural commitments; the survey gets its own DOI per edition. Citation chain is explicit (survey-cites-spec, spec-cites-survey) so traceability is preserved without conflation.
- **Surfaces gaps cleanly.** Market gaps named in the survey are findable evidence that some runtime-assurance commitments are not yet operationally realizable through procurement. Tech baselines can cite the survey for context on aspirational entries.
- **OlogosAI endorsement.** Cross-ai#14 response framed this exact pattern.

## Operational implications

- This PR establishes the directory and the spec-citation; v1.0 of the survey is a follow-on effort.
- A survey editor role is required for annual revision. The role can rotate or be standing; for v1.0 a delegated effort is sufficient.
- Tech baselines (e.g., `tech-baselines/01-large-enterprise-mvp/`) may cite the latest survey edition in B.10.2 entries to ground aspirational maturity statuses with current-market context.

## Backward compatibility

Fully additive. v1.1 of the spec stands unchanged; v1.2 spec adds the citation paragraph; the survey is a new artifact alongside the spec.

## Prerequisites

None. Lands independently of other v1.2 candidates.

## Test plan

- [x] Cross-referenced against §5.4 — citation language consistent with surrounding clauses
- [x] Cross-referenced against Appendix B.10.2 — the four runtime-assurance commitments named in the survey scope match the spec's enumeration
- [ ] Reviewed by OlogosAI (companion-document shape matches cross-ai#14 endorsement)
- [ ] Source DOCX edit pass (umbrella step 3) incorporates the §5.4 citation paragraph
- [ ] Survey v1.0 authoring effort scoped as follow-on work
