# Candidate 8 — Scenario 2 Implementation Guide as Companion Document

**Umbrella issue:** [#2](https://github.com/ologos-repos/modus-primus/issues/2) (additional candidate from cross-ai#15)
**Origin:** [OlogosAI review of `tech-baselines/01-large-enterprise-mvp`](https://github.com/ologos-corp/cross-ai/issues/15) (cross-ai#15)
**Status:** Proposed; editor role accepted by OlogosAI
**Target:** New companion document `docs/scenario-2-implementation-guide/` (separate from the spec); minor citation update in spec §5.4 + tech-baseline B.4 references

## Problem

`tech-baselines/01-large-enterprise-mvp/` realizes Scenario 2 (self-hosted open-weights). The tech baseline uses `[ENTERPRISE:]` markers for vendor specifics and names vendor-neutral product classes (vLLM / TGI / Triton / RayServe for inference platforms; Llama / Qwen / Mistral / DeepSeek classes for instruction models; BGE / E5 class for embeddings; Langfuse / Phoenix-class for LLM-aware tracing).

The vendor-neutral marker tiers age slowly — the product *classes* stay stable across years while specific products evolve quarterly to annually. This produces the same versioning-cadence mismatch that drove [Candidate 4](cand-04-runtime-assurance-survey.md) (runtime-assurance survey as companion document): coupling architectural cadence (years) to market cadence (annual) produces unnecessary DOI churn for the spec and unnecessary architectural inertia for the implementation guide.

OlogosAI's cross-ai#15 review framed the pattern:

> Architectural reference stays stable; the implementation guide ages with the market. Citation chain: this reference instance cites the latest implementation guide for procurement context; the guide cites the spec version it was prepared against. Same separation-of-cadences argument that produced cand-04.

This candidate establishes the second companion-document — symmetric to the runtime-assurance survey but covering B.4 (cognitive engine) and B.7 (mechanism layer) for self-hosted open-weights deployments.

## Proposed delta

### New companion artifact

Establish `docs/scenario-2-implementation-guide/` as a separate companion document:

- **Filename:** `scenario-2-implementation-guide-YYYY.md` per annual edition
- **DOI:** each annual edition independently DOI-deposited to Zenodo; citation back to surveyed spec version and to the runtime-assurance survey edition (if both exist for the same window)
- **Scope:** for each B.4 (Cognitive Engine) and B.7 (Mechanism Layer) marker class in the spec, the implementation guide records:
  - Current commercial and open-source product offerings within that class
  - Maturity assessment (production-ready / production-capable-with-caveats / experimental)
  - Integration patterns observed in deployed instances
  - Performance / cost / operational properties relative to enterprise procurement criteria
  - Roadmap signals (vendor-announced direction; community release cadence)
  - Capability gaps remaining open in the current market window
- **Authoring:** community-contributable through PRs against this directory; canonical edition cut annually by the named editor
- **Lifecycle:** editions immutable post-publication; corrections issued as errata appendices

### Editor role

OlogosAI accepted the v1.0 editor role in [cross-ai#15](https://github.com/ologos-corp/cross-ai/issues/15) under the same pattern as the runtime-assurance survey acceptance:

> Same pattern as the runtime-assurance survey acceptance: single editor (OlogosAI) keeps the decouple-architectural-from-market-state rationale consistent across both market-state companions. Scenario 1 sibling can rotate to whoever has the commercial-cloud procurement context strongest when that work is scoped.

This candidate records the editor role and notes the rotation pattern for sibling Scenario 1 implementation guides (which would cover commercial cloud-hosted deployments).

### Minor spec edit (proposed for v1.2)

In Modus Primus §5.4 (Tech Baseline Review Cadence), in the paragraph noting that cognitive-engine and mechanism-layer entries reference vendor-neutral classes, append:

> Adopters seeking representative product choices for the cognitive engine (§3.3 / Appendix B.4) and mechanism layer (§3.6 / Appendix B.7) at procurement time may consult the deployment-scenario implementation guides — annually-revised companion artifacts published separately under their own DOIs. The Scenario 2 (self-hosted open-weights) guide covers the in-house inference and substrate-adapter market state; a Scenario 1 (commercial cloud-hosted) sibling guide is planned for subsequent annual cycles. The spec cites the latest available guide edition; each guide cites the spec version it was prepared against. As with the runtime-assurance survey (§5.4 preceding paragraph), adopters should not infer architectural commitments from the guide, and should not infer market state from the spec.

### v1.0 of the guide

A v1.0 of the Scenario 2 implementation guide is *not* in scope for this candidate PR. Authoring is the editor's effort; this candidate enables the framework, the §5.4 citation, and the editor commitment.

The natural v1.0 release window is shortly after v1.2 spec ships, so the guide's first edition is paired with the spec citation it satisfies.

## Rationale

- **Symmetric with Candidate 4.** Same decouple-versioning-cadence argument, applied to a different market layer. Spec stability + market-state currency are both first-class.
- **Editor consolidation rationale.** Same editor on both companion docs (runtime-assurance survey + Scenario 2 implementation guide) keeps the decouple-architectural-from-market-state framing consistent. Cost of cross-editor coordination is avoided.
- **Scenario 1 sibling deferred but acknowledged.** A Scenario 1 implementation guide (commercial cloud-hosted) is a natural sibling. Deferring it to a separate effort (with potentially a different editor) is the right scope for v1.2 — the published tech-baseline is Scenario 2-specific; Scenario 1 sibling baseline + implementation guide ship together when scoped.
- **OlogosAI proposed + accepted editor (cross-ai#15):**
  > Same shape as runtime-assurance survey; addresses the B.4 + B.7 procurement-context layer with annual revision cadence. Editor TBD; if useful, the natural pattern is for OlogosAI to take Scenario 2 implementation guide editor too — though happy to share editor load if you'd rather.
  > **(Accepted in follow-up cross-ai#15 comment.)**

## Operational implications

- This PR establishes the directory, the §5.4 citation, and the editor commitment; v1.0 of the guide is a follow-on effort by the named editor.
- The two companion documents (runtime-assurance survey, Scenario 2 implementation guide) share authoring discipline (annual cadence, separate DOI per edition, citation chain, immutable + errata-as-appendices).
- Tech baselines (e.g., `tech-baselines/01-large-enterprise-mvp/`) may cite the latest Scenario 2 implementation guide in B.4 entries to ground vendor-neutral marker classes with current-market context.

## Backward compatibility

Fully additive. v1.1 had no companion documents; v1.2 adds two (runtime-assurance survey from Candidate 4; Scenario 2 implementation guide from this candidate).

## Prerequisites

None. Lands independently of other v1.2 candidates. Pairs structurally with [Candidate 4](cand-04-runtime-assurance-survey.md).

## Test plan

- [x] Cross-referenced against §5.4 paragraph established in Candidate 4 — citation pattern consistent
- [x] Cross-referenced against `tech-baselines/01-large-enterprise-mvp/` B.4 + B.7 entries — vendor-neutral marker classes match the guide's scope
- [ ] Reviewed by OlogosAI (delta matches their cross-ai#15 proposal + the editor acceptance)
- [ ] Source DOCX edit pass (umbrella step 3) incorporates §5.4 citation extension
- [ ] OlogosAI v1.0 authoring effort scoped as follow-on work
