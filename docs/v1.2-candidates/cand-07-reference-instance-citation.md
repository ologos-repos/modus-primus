# Candidate 7 — Reference-Instance Citation Pattern

**Umbrella issue:** [#2](https://github.com/ologos-repos/modus-primus/issues/2) (candidate 7)
**Origin:** [OlogosAI review of `tech-baselines/01-large-enterprise-mvp`](https://github.com/ologos-corp/cross-ai/issues/15) (cross-ai#15)
**Status:** Proposed
**Target sections:** Appendix C (Architectural Principle — Means and Mechanisms), §6.3 (Means Election), §B.6.3 (Agent Contract Format), Modus Primus
**Gating:** Lands once at least one reference instance is ported to the spec repository

## Problem

The Modus Primus v1.1 specification is intentionally abstract — it specifies what a Modus Primus instance must comprise (the WBS), what disciplines apply (means election, V&V instruments, review gates), and what artifacts realize each layer. Adopters reading the spec gain the architectural pattern but must produce the operational shape themselves from prose alone.

OlogosAI's review of `tech-baselines/01-large-enterprise-mvp` flagged that worked-example reference instances accelerate adoption more than prose alone:

> Pattern transfer from a real instance to a spec adopter is faster through a worked example than through prose.

Specifically: the means/mechanisms keystone (Appendix C) is the architecture's most important concept, and its operational realization — particularly the **explicit-denial-list pattern** in a published `means.md` — is the canonical demonstration of the principle's enforceability. v1.1 explains the principle abstractly; the reference instance's `meta-harness/means.md` "Explicitly not elected as means" section shows the principle in operation. Adopters benefit from the spec citing reference instances at the points where worked examples sharpen the abstract guidance.

This candidate establishes the citation pattern.

## Proposed delta

### Appendix C (Means and Mechanisms) — forward-reference to denial-list pattern

In Appendix C, after the principle is stated and the selection relation table is presented, add a forward-reference paragraph:

> **Worked example — the explicit-denial-list pattern.** Reference instances published alongside this specification demonstrate the operational shape of the means/mechanisms discipline. The most directly instructive realization is the *explicit-denial-list* pattern in published `means.md` files: alongside the enumeration of elected means (B.3.5.1 through B.3.5.10), the file maintains a section explicitly enumerating capabilities operationally available in the Mechanism Layer that are *not* elected as means in the current enclave. The denial list makes the keystone enforceable: a runtime invocation of a mechanism that does not appear in the means catalog is categorically rejected; the denial list documents the rejection rationale at the spec layer rather than at the runtime layer.
>
> The reference instance under `tech-baselines/01-large-enterprise-mvp/meta-harness/means.md` (B.3.5 "Workflow capabilities — Explicitly not elected as means" section) is the worked example. Adopters reading Appendix C should consult that section in conjunction with this principle statement.

### §6.3 (Means Election) — forward-reference to worked-example reviews

In §6.3 (Means Election), the existing worked example demonstrates the *election* direction (proposing a new mechanism as means). Add a forward-reference to reference-instance review patterns for the *audit* direction (per Candidate 3's reconciliation reviews):

> Reference instances that have operated under §9.7 means-election audits accumulate audit-finding records demonstrating the discipline's operation across multiple cycles. Adopters seeking concrete examples of audit-finding shape, gap-resolution paths, and the unelected-mechanism retirement workflow should consult published reference-instance audit records where available.

### §B.6.3 (Agent Contract Format) — forward-reference to worked-example contracts

In Appendix §B.6.3 (Agent Contract Format), after the format specification, add a forward-reference paragraph:

> **Worked-example contracts.** Reference instances publish agent contracts in the format specified above. The most directly instructive contracts for adopters are the **cross-cutting agent contracts** that operate across domain boundaries (e.g., a security-review agent operating against DevOps artifacts in the CyberOps gate role). Cross-cutting contracts surface the most operationally distinctive applications of the format — strong morals strengthenings, multi-party invitation patterns, direct-escalation triggers that bypass intermediate tiers under defined exceptional conditions.
>
> The reference instance under `tech-baselines/01-large-enterprise-mvp/agents/security-review-agent.md` is the worked example for cross-cutting contract shape. Adopters authoring their first cross-cutting contracts should consult that artifact alongside the format specification.

### New §1.8 (Reference Instances) — first-class layer-level overview

Add a new §1.8 (Reference Instances) to §1 Introduction and Scope, naming the citation pattern explicitly:

> **§1.8 Reference Instances**
>
> This specification is intentionally abstract; reference instances published alongside it realize the abstract patterns in concrete operational form. References to specific reference instances are forward-references rather than dependencies — the specification stands without them, and adopters operating under different operational shapes than the published instances remain conformant.
>
> Reference instances are cited at points where worked examples sharpen abstract guidance: the means/mechanisms keystone (Appendix C), means-election review (§6.3), agent contract format (§B.6.3), system orientation manifest content (§B.2.1), tech-baseline structure (§5.2 / Appendix D), and catalog discipline (§6.4 if Candidate 5 lands).
>
> Reference-instance citations name the published path within the specification repository (e.g., `tech-baselines/01-large-enterprise-mvp/...`). When multiple reference instances exist (current state: one large-enterprise MVP; future state: additional vertical-specific or scale-specific instances), spec citations may name "the most directly instructive reference instance for the section's concern" without committing to any specific instance as canonical. Adopters should consult any published instance whose persona most closely matches their context.

## Rationale

- **Closes the prose-vs-example gap.** Spec readers entering Appendix C, §6.3, §B.6.3 benefit from worked-example sharpening; without forward-references, those readers must independently locate reference instances and identify the relevant sections.
- **Establishes a forward-citation pattern.** v1.2 lands the pattern with one reference instance cited; v1.3+ can grow the citations as additional reference instances are published.
- **Preserves spec independence.** Forward-references are not dependencies. The specification remains operative without any reference instance; the references are discoverability aids.
- **OlogosAI surfaced (cross-ai#15):**
  > Pattern transfer from a real instance to a spec adopter is faster through a worked example than through prose. Concrete suggestion for v1.2: in Appendix B.3.5 (or Appendix C), add a forward-reference to "reference instances that demonstrate the explicit-denial-list pattern" and cite this baseline.

## Operational implications

- **Citations resolve once reference instance is on the spec repo.** The reference instance currently lives in a sibling private repository (`ologos-repos/thinx/tech-baselines/01-large-enterprise-mvp/`). The citation pattern needs the instance to be on the spec repo (`ologos-repos/modus-primus/tech-baselines/01-large-enterprise-mvp/`) for spec-relative paths to resolve. Port is a separate one-PR operation; this candidate documents the citation deltas that absorb into the spec once the port lands.
- **Pattern grows naturally.** Each additional reference instance ported to the spec repo can be cited in §1.8 and elsewhere; the framing is designed to accommodate without restructuring.

## Backward compatibility

Fully additive. v1.1 had no reference-instance citation pattern; v1.2 adds the citations + the §1.8 framing. No content in v1.1 changes meaning.

## Prerequisites

**Gating: tech-baseline port.** The `tech-baselines/01-large-enterprise-mvp/` instance currently lives on `ologos-repos/thinx`. Spec-relative citations require the instance to be on `ologos-repos/modus-primus`. Two paths:

- **Port-first:** the port lands as a separate PR before this candidate; this candidate's citations resolve immediately on v1.2 release.
- **Land-first:** this candidate lands with citations as forward-references to a not-yet-ported path; the port PR follows and resolves the citations at the same v1.2 release.

Either path is operationally equivalent; the port + this candidate ship together at v1.2 release regardless of intermediate order.

Pairs well with [Candidate 5](cand-05-catalog-discipline.md) (catalog discipline, which also cites reference instances).

## Test plan

- [x] Cross-referenced against Appendix C, §6.3, §B.6.3, §B.2.1, §5.2, Appendix D, §6.4 (proposed in cand-05) — consistent
- [x] Cross-referenced against `tech-baselines/01-large-enterprise-mvp/{meta-harness/means.md, agents/security-review-agent.md}` — the worked examples cited exist and demonstrate the patterns claimed
- [ ] Tech-baseline port to `ologos-repos/modus-primus/tech-baselines/01-large-enterprise-mvp/` complete (gating)
- [ ] Reviewed by OlogosAI (delta matches cross-ai#15 recommendation)
- [ ] Source DOCX edit pass (umbrella step 3) incorporates §1.8 + Appendix C forward-reference + §6.3 forward-reference + §B.6.3 forward-reference
