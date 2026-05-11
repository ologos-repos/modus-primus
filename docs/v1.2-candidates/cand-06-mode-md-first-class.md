# Candidate 6 — `mode.md` as First-Class Boot Manifest Artifact

**Umbrella issue:** [#2](https://github.com/ologos-repos/modus-primus/issues/2) (candidate 6)
**Origin:** [OlogosAI review of `tech-baselines/01-large-enterprise-mvp`](https://github.com/ologos-corp/cross-ai/issues/15) (cross-ai#15)
**Status:** Proposed
**Target sections:** §2.3 (Five-M Decomposition) — promote `mode.md` to a sibling concept; §3.1 (System Orientation) — recognize `mode.md` as the layer's canonical artifact, Modus Primus

## Problem

Modus Primus v1.1 §3.1 specifies the "System Orientation" layer as `mode.md`, a single artifact establishing system identity, governing philosophy, and federation posture, read at boot or session start. v1.1 Appendix B.2.1 enumerates its content (System identity, Governing philosophy, Meta-harness declaration, Operational orientation, Constraint inheritance model, Federated hierarchy declaration, Execution doctrine, Admissibility principles, Delegation philosophy, Root orchestration posture).

What v1.1 does not surface: **`mode.md` is structurally distinct from the five-M layer**. The five-M files (mind, morals, mission, memory, means) are purposive declarations about reasoning posture, ethical constraint, system telos, retention policy, and capability repertoire — domains the system commits to. `mode.md` is a different category of artifact: it is a **boot manifest** that orients the system *before* the five-M are read, declaring system identity, federation tier binding, and orchestration posture so the rest of the meta-harness load can interpret itself coherently.

OlogosAI's review of `tech-baselines/01-large-enterprise-mvp/meta-harness/mode.md` surfaced the distinction:

> The `meta-harness/mode.md` file is structurally interesting: it's B.2.1 in the spec WBS but conceptually a *seventh* meta-harness file alongside the five-M plus `means.md`. It carries system identity, governing philosophy, meta-harness declaration, operational orientation, constraint inheritance, federation declaration, execution doctrine, admissibility principles, delegation philosophy, root orchestration posture. Effectively a *boot manifest* — orienting the system at session start before the 4M+1 are read.
>
> This is a thoughtful design pattern. v1.2 candidate: surface mode.md as a first-class meta-harness artifact in §2.3 or §3.1 rather than tucking it under "System Orientation" alongside everything else. Adopters will copy it; making it discoverable in the spec accelerates adoption.

Currently `mode.md` is documented as one row in the Appendix B WBS table; readers proceeding through the spec linearly encounter the five-M decomposition in §2.3 and may not realize that `mode.md` is the prerequisite artifact whose absence breaks the rest of the load.

## Proposed delta

### §2.3 (Five-M Decomposition) — promote `mode.md` recognition

Currently §2.3 introduces the meta-harness layer as "comprising five files (mind, morals, mission, memory, means)." Revise to recognize `mode.md` as the boot manifest that precedes the five-M:

> **§2.3 The Meta-Harness Layer: Boot Manifest and Five-M Decomposition**
>
> The meta-harness layer comprises a boot manifest (`mode.md`) and five purposive declarations (`mind.md`, `morals.md`, `mission.md`, `memory.md`, `means.md`) that together establish the system's disposition.
>
> The boot manifest reads first. `mode.md` declares system identity, federation tier binding, governing philosophy, operational orientation, and orchestration posture — the orienting context that lets the five-M be interpreted coherently. A reader (human or runtime) entering the meta-harness without first reading `mode.md` lacks the federation context to interpret the purposive declarations correctly.
>
> The five-M reads next, hierarchically: mind grounds morals, morals grounds mission, mission grounds memory, memory grounds means. The order is read-order; revision order is independent (any of the five may be revised without re-revising the others, subject to inheritance consistency).
>
> - **mode.md** declares *where the system is, structurally* (identity, tier, federation context). Read once, stable across runtime, revised through WBS architectural review (§9.1).
> - **mind.md** declares how the system reasons toward its mission
> - **morals.md** declares what the system must not do toward any end
> - **mission.md** declares what the system is for
> - **memory.md** declares what is worth remembering given what the system is for
> - **means.md** declares the system's purposive repertoire for advancing its mission within its morals
>
> The boot manifest is not a sixth purposive declaration. The five-M unity (Modus Primus v1.1 §2.3) holds for the five purposive files; `mode.md` is a *structural* declaration that establishes the context for the purposive layer. The distinction is load-bearing: revising `mode.md` (changing tier binding, federation context, or orchestration posture) requires re-validation of inheritance from the parent Modus tier; revising the five-M files (within the current tier binding) is governed by their respective owners under §9.1.

### §3.1 (System Orientation) — recognize `mode.md` as canonical artifact for the layer

Currently §3.1 says: "A single artifact (mode.md) that establishes system identity, governing philosophy, and federation posture." Tighten the framing:

> **§3.1 System Orientation (Boot Manifest)**
>
> The system orientation layer is realized by a single canonical artifact, `mode.md` — the **boot manifest**. The manifest declares system identity (which Modus tier instance this is), governing philosophy (the reasoning canon under which this instance operates), federation posture (where the instance sits in the tier hierarchy and how it relates to peers), and orchestration posture (how root-level orchestration is conducted within this instance).
>
> The manifest is read at boot and at session start; it is stable across runtime within the current tier binding. Revisions are governance acts requiring WBS architectural review (§9.1) because manifest changes propagate to dependent layers (cognitive engine binding, federation contracts, execution-policy declarations).
>
> The content schema for `mode.md` is specified in Appendix B.2.1.

### Appendix B.2.1 — minor framing tightening

The Appendix B.2.1 enumeration is unchanged content-wise. Add a one-sentence preamble emphasizing the boot-manifest framing:

> **B.2.1 mode.md (Boot Manifest)**
>
> The canonical artifact for the system orientation layer (§3.1). Read first; orients the rest of the meta-harness load. Content schema:

(rest of B.2.1 unchanged)

## Rationale

- **Surfaces the structural-vs-purposive distinction.** v1.1's "five-M plus mode.md" framing treats them as peers; this candidate establishes the right relationship — `mode.md` is the structural prerequisite for interpreting the purposive layer.
- **Makes the prerequisite discoverable.** Adopters reading the spec linearly encounter §2.3 (five-M) before §3.1 (system orientation) and may treat `mode.md` as auxiliary; the §2.3 promotion makes the reading-order requirement explicit.
- **Worked-example reinforcement.** The reference instance's `meta-harness/mode.md` already realizes the boot-manifest shape (10 subsections covering identity, philosophy, declaration, orientation, inheritance, federation, doctrine, admissibility, delegation, orchestration); this candidate aligns the spec language with what the reference instance already implements.
- **OlogosAI surfaced (cross-ai#15):**
  > Surface mode.md as a first-class meta-harness artifact in §2.3 or §3.1 with the "boot manifest" framing. Adopters will copy it; making it discoverable in the spec accelerates adoption.

## Operational implications

- **No content change to `mode.md` instances.** The reference instance's `mode.md` already satisfies the boot-manifest framing.
- **No new artifact required.** This is a framing tightening, not a new layer.
- **Revision governance unchanged.** `mode.md` revisions remain WBS architectural reviews (§9.1) per v1.1; the candidate makes the rationale (manifest changes propagate to dependent layers) explicit.

## Backward compatibility

Fully additive. v1.1 instances' `mode.md` files continue to satisfy v1.2 without changes (content schema is unchanged). The framing distinction is documentary; existing instances are conformant.

## Prerequisites

None. Lands independently of other v1.2 candidates.

## Test plan

- [x] Cross-referenced against §2.3, §3.1, §9.1, Appendix B.2.1 — consistent with surrounding clauses
- [x] Cross-referenced against `tech-baselines/01-large-enterprise-mvp/meta-harness/mode.md` — the reference instance already realizes the boot-manifest shape
- [ ] Reviewed by OlogosAI (delta matches cross-ai#15 recommendation)
- [ ] Source DOCX edit pass (umbrella step 3) incorporates §2.3 promotion + §3.1 tightening + B.2.1 preamble
