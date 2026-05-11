# v1.2 candidates

Working space for proposed revisions feeding the v1.2 spec revision umbrella ([#2](https://github.com/ologos-repos/modus-primus/issues/2)).

## Purpose

Each markdown file in this directory captures one proposed v1.2 change: the delta, the recommended spec placement, the rationale, and any prerequisites. PRs land each candidate as a discrete artifact, reviewable independently. When the v1.2 source DOCX revision begins, this directory is the input set for the canonical edit.

## Lifecycle

1. **Candidate proposed.** PR against this directory adds a candidate file. Discussion in PR thread.
2. **Candidate ratified.** PR merges; the candidate is part of the v1.2 input set.
3. **Source DOCX revision pass.** A single coordinated PR translates ratified candidates into source DOCX edits, regenerates the PDF, and updates README citations.
4. **Zenodo re-deposit.** v1.2 PDF deposited to Zenodo with new DOI; README updated to add v1.2 entry to the document table.
5. **Candidate files retained.** Files in this directory persist as the historical record of v1.2 input; they are not deleted on v1.2 release.

## Current candidates

| File | Title | Status |
|---|---|---|
| (this README) | v1.2 candidates directory | — |
| _populated as PRs land_ | | |

## Out of scope

Source DOCX edits, PDF regeneration, and Zenodo deposit are not in this directory. Those happen in the source DOCX revision pass (umbrella step 3 above) against the spec sources at the repo root.
