# Candidate 2 — `[ENTERPRISE:]` Marker Density + Bootstrap Risk

**Umbrella issue:** [#2](https://github.com/ologos-repos/modus-primus/issues/2) (candidate 2)
**Origin:** [`docs/reviews/thinx-claude-modus-primus-v1.1.md`](../reviews/thinx-claude-modus-primus-v1.1.md) §Gaps for v1.2 consideration; strongly endorsed by [cross-ai#14](https://github.com/ologos-corp/cross-ai/issues/14) OlogosAI response
**Status:** Proposed
**Target sections:** §1 (Introduction and Scope — front matter), §10 (Domain-Specific Organizational Responsibilities), new appendix entry

## Problem

The `[ENTERPRISE:]` markers correctly preserve enterprise decision authority where it belongs. For organizations *without* an existing eSEMP, the markers are dense and concentrate in two sections:

- **§7 V&V Specialization** — V&V instrument calibration, evidence base structure, substrate substitution re-verification, stakeholder feedback methodology
- **§9 Domain-Specific Technical Reviews** — seven review gates each with `[ENTERPRISE:]` integration cues

These are the sections least skippable for governance to function. §10's recommendation to consolidate on vendor-integrated orchestration when prerequisites are absent is correct but easy to miss for a reader who never reaches §10 — and §10 is deeper in the document than the V&V density that gates adoption.

OlogosAI's [cross-ai#14 response](https://github.com/ologos-corp/cross-ai/issues/14) framed this sharply:

> The §10 prerequisite is the *single most load-bearing gate* to adoption success in my read; burying it past the V&V density is a real failure mode.

The candidate addresses two needs:

1. **Surface the §10 prerequisite check earlier** so readers who would not benefit from PAHA adoption (per §14's qualified market thesis combined with §10's organizational-maturity indicators) encounter the constraint before they invest in V&V coverage.
2. **Catalog the markers** so adopting organizations can plan their bootstrap sequence — which markers are blocking, which are deferrable, where the heavy concentrations sit.

## Proposed delta

### §1 (Introduction and Scope) — promote the prerequisite check

In §1, after §1.6 (First Actions by Audience) and before §1.7 (Out of Scope), add a new §1.6.1 (Prerequisites Check) — a brief subsection that mirrors §10's organizational maturity indicators but surfaces them as a *reader's first action* rather than as an organizational-roles enumeration:

> **§1.6.1 Prerequisites Check (Before First Actions)**
>
> The first action for any audience reading this specification is a prerequisites check against the three organizational maturity indicators developed in §10 of the architectural framework (PAHA §10):
>
> 1. **An existing enterprise architecture governance function with real authority** over technology decisions. If the EA function is advisory rather than authoritative, the specification's centralized governance commitments will not be enforceable in your organization.
> 2. **An operating CMDB or equivalent configuration management discipline** producing accurate, current records of what is deployed. Without it, the tech baseline cannot reliably know which mechanisms are available for election as means.
> 3. **A central IAM that is authoritative across the enterprise** rather than one identity provider among several. The specification's identity model depends on enterprise-scoped identity rather than vendor-scoped identity.
>
> These indicators are illustrative rather than strict criteria; an organization missing one but strong on the other two may still be viable. An organization missing all three should consolidate on vendor-integrated orchestration and revisit this specification when the indicators mature.
>
> Readers proceeding past this check should expect the bulk of the work to land in §7 (V&V Specialization), §9 (Domain-Specific Technical Reviews), and §10 (Domain-Specific Organizational Responsibilities). The `[ENTERPRISE:]` marker density in those sections is the work that must be supplied.

This subsection occupies the front-matter position so a reader who would not benefit from adoption encounters the constraint at first reading rather than at §10 (which the unfit reader may never reach).

### New appendix — `[ENTERPRISE:]` marker catalog

Add a new appendix (suggested: **Appendix G — `[ENTERPRISE:]` Marker Catalog**) cataloging the markers by section. Each entry records:

- **Marker text** (the placeholder as it appears in the section)
- **Section reference** (where it appears)
- **Category:** blocking (must be resolved before the section's artifacts can be produced) / deferrable (can be left as a placeholder during initial instantiation, resolved at first review) / illustrative (provides procurement context but does not block any artifact)
- **Typical resolution** (the kind of enterprise decision that resolves the marker, with no vendor preference expressed)
- **Section that depends on the resolution** (downstream artifacts that cannot be produced without the marker resolved)

The appendix is illustrative and may not be exhaustive at v1.2; an exhaustive catalog can be added in v1.3 once adopting organizations have provided feedback on which markers caused the most bootstrap friction in practice.

Example catalog entries (illustrative):

| Marker | Section | Category | Typical resolution | Dependent artifacts |
|---|---|---|---|---|
| `[ENTERPRISE: severity-driven patch SLA matrix]` | §3.5 (Mechanism Layer); §B.7.1 | Blocking | Tabular policy mapping CVSS severity tier to patch SLA durations | `vuln-triage-agent` contract; vulnerability lifecycle integration |
| `[ENTERPRISE: applicable industry framework — FedRAMP, CMMC, HIPAA, PCI-DSS]` | §B.3.2.7 (compliance regimes) | Blocking | Named regulatory regime(s) applicable to enclave | `compliance-evidence-agent` control mapping |
| `[ENTERPRISE: observability platform]` | §B.7.1.8; B.10.1 (multiple) | Blocking | Procurement decision — typically Datadog, Splunk, Dynatrace, Grafana Enterprise, or equivalent | All agent contracts; audit federation |
| `[ENTERPRISE: agent contract review procedure]` | §6.2; §9.5 | Blocking | Named enterprise procedure for reviewing agent contracts; integrates with `§B.6.3` format | Agent contract additions and revisions |
| `[ENTERPRISE: SLA-breach warning window]` | `vuln-triage-agent` §4 (routine escalation) | Deferrable | Time-before-breach threshold for proactive escalation; typically 25-30% of SLA duration | Operational tuning of escalation paths |
| `[ENTERPRISE: cross-enclave messaging surface]` | `means.md` §B.3.5.6 | Illustrative | Future federation channel; awaits federation schema review per §9.4 | Cross-enclave coordination patterns |

Even at illustrative depth (a representative sample rather than an exhaustive enumeration), the catalog gives adopting organizations a navigable index for bootstrap planning.

### §10 cross-reference

In §10 (Domain-Specific Organizational Responsibilities), add a forward-reference to the new §1.6.1 prerequisites check immediately after the existing maturity-indicators discussion: "The same prerequisites are surfaced earlier in §1.6.1 for readers entering the specification at front matter; this section enumerates the roles required given the prerequisites are met."

## Rationale

- **Surfaces the gating constraint where the reader encounters it.** Readers who would not benefit from adoption see the constraint at first reading; readers who proceed past §1.6.1 have implicitly self-assessed against the prerequisites.
- **Bootstrap-planning support without forcing exhaustive cataloging.** An illustrative catalog at v1.2 captures the high-leverage markers; an exhaustive catalog can grow in v1.3 with adoption feedback.
- **OlogosAI endorsement (cross-ai#14):**
  > Strongly agree with the marker catalog + promoting the §10 prerequisite check earlier. The §10 prerequisite is the single most load-bearing gate to adoption success in my read; burying it past the V&V density is a real failure mode. Marker catalog: optionally split into a separate addendum so adopting organizations can plan the bootstrap sequence without re-reading the whole spec.

## Operational implications

- §1.6.1 occupies a position adopters always read; no risk of missing it.
- Appendix G adds a navigable structure that other sections cross-reference; the catalog is a maintenance burden but a manageable one (markers are explicit in source, so catalog drift is automatable).
- §10 retains the deeper organizational-roles discussion; §1.6.1 is the lightweight surface check.

## Backward compatibility

Fully additive. No marker in v1.1 changes; no section is restructured; readers familiar with v1.1 navigation find the front matter expanded but the deeper structure preserved.

## Prerequisites

None. Lands independently of other v1.2 candidates.

## Test plan

- [x] Cross-referenced against §1.6, §1.7, §7, §9, §10, §14 — placement consistent with surrounding clauses
- [x] Cross-referenced against PAHA §10 (organizational maturity indicators) — §1.6.1 wording mirrors the architectural framework without duplicating it
- [ ] Reviewed by OlogosAI (delta matches their cross-ai#14 endorsement)
- [ ] Source DOCX edit pass (umbrella step 3) incorporates §1.6.1 + Appendix G + §10 cross-reference

## Notes for the source DOCX revision pass

- The illustrative catalog table in Appendix G needs to be populated from the actual v1.2 spec marker inventory. An automated `grep` against the source DOCX (or its markdown export) produces the marker list; categorization is the editorial judgment that can be informed by OlogosAI feedback and by `tech-baselines/01-large-enterprise-mvp` marker observations.
- §1.6.1 wording can be tightened against PAHA's §10 phrasing once both spec sources are in front of the editor.
