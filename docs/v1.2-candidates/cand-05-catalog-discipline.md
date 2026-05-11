# Candidate 5 — Catalog Discipline as First-Class WBS Concern

**Umbrella issue:** [#2](https://github.com/ologos-repos/modus-primus/issues/2) (candidate 5)
**Origin:** [OlogosAI review of `tech-baselines/01-large-enterprise-mvp`](https://github.com/ologos-corp/cross-ai/issues/15) (cross-ai#15)
**Status:** Proposed
**Target sections:** §6 (Engineering Specialization) — new §6.4 (or absorbed into §9.5 expansion + Appendix E section), Modus Primus

## Problem

The Modus Primus v1.1 §9.5 Agent Contract Review specifies the gate criteria for evaluating new and revised agent contracts (inheritance correctness, operational coherence) but does not specify the operational discipline for managing the agent catalog as it evolves over time:

- **Additions** — beyond passing review, what governs the introduction of an agent into the catalog? How do additions interact with the means/mechanisms keystone?
- **Retirements** — what audit-trail-transfer obligations follow agent retirement? How are dependent invocation chains handled?
- **Revisions** — permission-scope expansions vs narrowings; what is the justification standard for each? How are revisions coordinated with downstream consumers (other agents that invoke the revised one)?

The thinx-Claude review of v1.1 implemented this discipline in `tech-baselines/01-large-enterprise-mvp/agents/agents.md` as a "Catalog discipline" section. OlogosAI's review of the reference instance flagged the absence in the spec:

> `agents.md` lines 47–53 has a "Catalog discipline" section covering additions, retirements, revisions — including permission-scope-change justification, narrowing-doesn't-require-justification, audit-trail-transfer-on-retirement. None of this is in Modus Primus v1.1's §6.3 (Agent Contract Format) or §9.5 (Agent Contract Review). It's operationally important and was clearly hard-won from real work.

This candidate captures the discipline as a first-class spec concern.

## Proposed delta

### New §6.4 (Catalog Discipline)

Add a new §6.4 (Catalog Discipline) under §6 Engineering Specialization, immediately following §6.3 Means Election:

> **§6.4 Catalog Discipline**
>
> The agent catalog evolves over time as new agents are introduced, existing agents are revised, and unused agents are retired. Three operational disciplines govern catalog evolution beyond the inheritance correctness and operational coherence criteria evaluated at the Agent Contract Review gate (§9.5).
>
> **6.4.1 Additions.** Agent additions to the catalog require a contract review (§9.5) before the agent may be registered in the Secundus capability registry. Additions interact with the means/mechanisms keystone: an agent that elects means previously not used by any other agent in the enclave triggers a means-election review (§9.7) for those means before the agent's contract can be registered. The two reviews may be conducted concurrently but both must approve. This sequencing is what prevents agent introductions from silently expanding the system's purposive disposition through the back door.
>
> **6.4.2 Revisions.** Permission-scope expansions (broadening the means authorized, expanding data scope, broadening operational scope, raising trust level) require explicit justification documented in the revision proposal. The justification is evaluated for proportionality (does the expansion match the agent's mission scope?) and necessity (is the expansion required by recent operational evidence, or speculative?). Permission-scope narrowings (narrowing means, restricting scope, lowering trust level, strengthening morals constraints) do not require justification but do require review for downstream coherence — agents that invoke the revised agent may need their own contracts updated to reflect the narrowed scope. The asymmetry is intentional: the cost of unjustified expansion is high (silent capability creep); the cost of narrowing is operational rework, which is observable.
>
> **6.4.3 Retirements.** Agent retirement requires a documented successor (or explicit declaration that no successor is needed), an audit-trail-transfer plan per the post-retirement obligations in the agent contract's lifecycle section, and a deregistration from the Secundus capability registry. Audit retention obligations survive retirement; the retired agent's audit identity continues to satisfy regulatory retention until the retention window closes. Successor agents (when present) inherit a provenance pointer to the retired agent's audit trail.
>
> **6.4.4 Worked-example reference.** Reference instances such as the published large-enterprise MVP baseline (under `tech-baselines/01-large-enterprise-mvp/agents/agents.md` "Catalog discipline" section) demonstrate the operational shape these disciplines take in concrete catalogs. Adopters should consult worked examples in conjunction with this §6.4.

### §9.5 cross-reference

In §9.5 (Agent Contract Review), the existing inheritance correctness + operational coherence criteria are retained as the gate criteria for individual contract decisions. Add a sentence at the end of §9.5 cross-referencing the catalog disciplines as the broader operational context:

> The contract review evaluates an individual contract against the gate criteria; the catalog disciplines in §6.4 govern the operational integration of the contract into the broader agent catalog (means-election sequencing for additions, justification standards for revisions, audit-trail transfer for retirements). Reviewers reading §9.5 should familiarize themselves with §6.4 before chairing reviews.

## Rationale

- **Surfaces hard-won operational discipline.** The discipline emerged from operating a real catalog under governance constraints; capturing it in the spec prevents adopters from rediscovering it through their own incidents.
- **Closes a gap in §6 Engineering Specialization.** Five subsections (substrate volatility cadence, agent contract authoring, means election, federation schema evolution, runtime assurance engineering) cover authoring + election + evolution + assurance, but not catalog-level discipline. §6.4 closes the gap symmetrically.
- **Worked-example pattern.** The reference-instance citation in §6.4.4 establishes a pattern of forward-referencing worked examples — consistent with [Candidate 7 (reference-instance citation pattern)](cand-07-reference-instance-citation.md) if that candidate also lands.
- **OlogosAI surfaced (cross-ai#15):**
  > Add §6.4 (or Appendix E.2) capturing catalog discipline as a first-class WBS concern, citing the reference-instance section as worked example.

## Operational implications

- The means-election sequencing for catalog additions (§6.4.1) operationalizes the keystone discipline — the two reviews can be concurrent, but both must approve. This is a small process commitment with high architectural value.
- The justification asymmetry for revisions (§6.4.2) is the discipline's most important commitment. Adopters reading only §9.5 may miss it; §6.4 makes it explicit and grep-able.
- The retirement provenance-pointer pattern (§6.4.3) is critical for cross-audit-window continuity. Without it, retired-then-replaced agents create discontinuities in audit retrospection.

## Backward compatibility

Fully additive. v1.1 said nothing about catalog discipline; v1.2 makes it explicit. Existing agent catalogs continue to operate; new disciplines apply to additions, revisions, and retirements that occur after v1.2 adoption.

## Prerequisites

None. Lands independently of other v1.2 candidates. Pairs naturally with [Candidate 7](cand-07-reference-instance-citation.md) (reference-instance citation pattern) if both ship.

## Test plan

- [x] Cross-referenced against §6.3, §9.5, §9.7, §B.6.3, Appendix C — consistent with surrounding clauses
- [x] Cross-referenced against `tech-baselines/01-large-enterprise-mvp/agents/agents.md` Catalog discipline section — the §6.4 wording is a spec abstraction of the worked example, not a copy
- [ ] Reviewed by OlogosAI (delta matches cross-ai#15 recommendation)
- [ ] Source DOCX edit pass (umbrella step 3) incorporates §6.4 + §9.5 cross-reference
