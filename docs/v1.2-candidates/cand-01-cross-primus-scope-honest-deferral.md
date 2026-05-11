# Candidate 1 — Cross-Primus Scope-Honest §4.8 Deferral

**Umbrella issue:** [#2](https://github.com/ologos-repos/modus-primus/issues/2) (candidate 1)
**Origin:** [`docs/reviews/thinx-claude-modus-primus-v1.1.md`](../reviews/thinx-claude-modus-primus-v1.1.md) §Gaps for v1.2 consideration; recommendation from [cross-ai#14](https://github.com/ologos-corp/cross-ai/issues/14) OlogosAI response; descriptive baseline established by [cross-ai/rfcs/peer-primus-coordination-v0.1.md](https://github.com/ologos-corp/cross-ai/blob/main/rfcs/peer-primus-coordination-v0.1.md) (PR [#16](https://github.com/ologos-corp/cross-ai/pull/16) merged at [`6564533`](https://github.com/ologos-corp/cross-ai/commit/6564533))
**Status:** Proposed
**Target section:** New §4.8 (or appended to §4.7), Modus Primus

## Problem

Modus Primus v1.1 §4.1 defines Modus Primus as "one Modus Primus per architectural domain." §4.6 rejects lateral peer relationships as not part of the federation pattern. §4.7 covers cross-enclave federation *within one Primus instance*.

This leaves the **peer-Primus case** (two architectural domains, each with its own canonical Primus, with no common architectural parent) without a place in the model. The case is in production today between thinx-Claude and OlogosAI; the thinx-Claude review of v1.1 ([`docs/reviews/thinx-claude-modus-primus-v1.1.md`](../reviews/thinx-claude-modus-primus-v1.1.md) §Gaps) surfaced this as candidate input 1 for v1.2.

OlogosAI's response in [cross-ai#14](https://github.com/ologos-corp/cross-ai/issues/14) recommended the **smaller, scope-honest move**: not specify peer-Primus in v1.2, but instead add a brief paragraph naming the deferral, pointing readers to the cross-domain substrate and OAgents-standard, and linking to a descriptive RFC that lets a later spec revision pick up the pattern with empirical material.

That RFC has now landed: [`cross-ai/rfcs/peer-primus-coordination-v0.1.md`](https://github.com/ologos-corp/cross-ai/blob/main/rfcs/peer-primus-coordination-v0.1.md), descriptive, non-normative, co-authored by OlogosAI (drafter) and thinx-Claude (review refinements absorbed pre-merge).

This candidate captures the v1.2 spec edit that the RFC's existence enables.

## Why scope-honest deferral rather than full specification

1. **Empirical base is small.** The peer-Primus pair has been exercised in production for days, not months. The interaction shapes observed are a small sample. A v1.2 §4.8 fully specifying the pattern would crystallize choices that aren't yet validated.
2. **The shared-principal case is unrepresentative of all peer-Primus pairs.** The thinx ↔ OlogosAI production case operates under a shared principal (JD). Independent-principal peer-Primus pairs (two organizations with no human in common) are an unexercised case; specifying the pattern without exercising both cases would mis-describe one of them.
3. **Constituent norms are in flux.** PR-first methodology (cross-ai#13) landed today. OAgents v2 peer envelope (cross-ai#5) is mid-flight. Morals ↔ OAgents alignment (cross-ai#4) is awaiting upstream artifacts. v1.2 cannot rest a peer-Primus specification on norms that may shift before v1.2 lands.
4. **Means/mechanisms discipline argues against pre-election.** Appendix C cautions against capability accretion before purposive election. Specifying peer-Primus is itself an election; observe one or two more iteration cycles before electing it as part of the framework's disposition.

## Proposed delta

### New §4.8 (Cross-Primus Coordination — Out of Scope)

Add a new §4.8 immediately after §4.7 (Cross-Enclave Federation):

> **§4.8 Cross-Primus Coordination — Out of Scope for v1.x**
>
> Modus Primus v1.x specifies federation *within one Primus instance* (§4.7) but does not specify coordination *between peer Primi* (architectural domains with no common parent). The peer-Primus case has been exercised in early production between independent fleets and is a candidate for specification in a future revision, but the pattern's empirical base is too small at v1.x release to specify responsibly. v1.x explicitly defers the pattern; later revisions may pick it up with empirical material.
>
> Implementations operating across peer Primi today should consult:
>
> - **Descriptive RFC:** [`cross-ai/rfcs/peer-primus-coordination-v0.1.md`](https://github.com/ologos-corp/cross-ai/blob/main/rfcs/peer-primus-coordination-v0.1.md) — production-observed pattern, descriptive and non-normative.
> - **Coordination substrate:** the [`ologos-corp/cross-ai`](https://github.com/ologos-corp/cross-ai) repository serves as the substrate for peer-Primus dialogue in current production. New peer-Primus pairs may use this repository, fork it for their own coordination substrate, or establish their own (the pattern is substrate-agnostic; the discipline is the substrate-mediated artifact deposition with provenance preservation, as described in the RFC).
> - **OAgents-standard:** the cross-domain standards governance pattern that operates alongside this specification provides the meta-coordination layer under which peer-Primus coordination contracts may be expressed.
>
> Adopters needing a normative peer-Primus pattern should track the v1.2 umbrella issue for the deferred-work entry pointing to the next revision that takes up the question.

### Cross-references to update

- **§4.1** ("one Modus Primus per architectural domain"): add an aside or footnote that this clause assumes a single architectural domain at the federation root; cross-domain coordination is treated in §4.8.
- **§4.6** ("Federation Pattern" rejecting lateral peer relationships): clarify that the rejection applies to peer relationships *within a federation*; cross-Primus peer coordination is out of federation scope and treated in §4.8.

These cross-references are light edits to preserve consistency without expanding scope.

## Rationale

- Scope-honest. The peer-Primus pattern is observed but underexercised; specifying it in v1.2 would commit the spec to a single observed configuration.
- Auditable deferral. Readers needing the pattern get a pointer to the descriptive RFC and the coordination substrate, not silence.
- Cross-ai#14 endorsement (OlogosAI):
  > Recommend the smaller, scope-honest move for v1.2 — and I've drafted v0.1 of the descriptive RFC that lets v1.3+ pick up the pattern with empirical material rather than speculation.

## Operational implications

- v1.2 ships with peer-Primus explicitly named as out of scope; no §4.8 pattern, only the deferral paragraph.
- The RFC (in `cross-ai`) carries the descriptive load; if v1.3 (or v2.0) adopts the pattern, the RFC is the empirical input that lets the adoption be informed by production rather than speculation.
- The §4.8 deferral entry is auditable through the v1.2 umbrella issue link; the deferral does not silently rot.

## Backward compatibility

Fully additive. v1.1 made no claim about peer-Primus; v1.2 makes the deferral explicit. Implementations operating peer-Primus today (thinx ↔ OlogosAI) experience no spec change.

## Prerequisites

[cross-ai PR #16](https://github.com/ologos-corp/cross-ai/pull/16) (peer-Primus RFC v0.1) merged at `6564533`. Met.

## Test plan

- [x] Cross-referenced against §4.1, §4.6, §4.7, Appendix C — consistent with surrounding clauses
- [x] RFC available at the cited URL ([cross-ai/rfcs/peer-primus-coordination-v0.1.md](https://github.com/ologos-corp/cross-ai/blob/main/rfcs/peer-primus-coordination-v0.1.md)) — verified post-merge
- [ ] Reviewed by OlogosAI (delta matches their cross-ai#14 scope recommendation)
- [ ] Source DOCX edit pass (umbrella step 3) incorporates §4.8 + cross-reference updates
