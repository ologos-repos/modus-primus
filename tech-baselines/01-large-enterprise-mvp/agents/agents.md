# Agent Catalog — Tech Baseline 01

Canonical list of Modus Tertius agents in this enclave. Each agent has an authored contract in this directory conforming to Modus Primus v1.1 Appendix E. Catalog ordering is by domain anchor (DevOps → ITIO → CyberOps) and within each anchor by typical invocation order in the corresponding enterprise process.

## DevOps (4)

Anchored to PR-gated trunk-based development, CI/CD with mandatory quality gates, and release management.

| Agent | File | Process anchor | Mission summary | Owner |
|---|---|---|---|---|
| `coder-agent` | [`coder-agent.md`](coder-agent.md) | SSDLC implementation phase; PR authoring against repository conventions | Generate, refactor, and analyze code within bounded repositories. | Engineering Productivity |
| `reviewer-agent` | [`reviewer-agent.md`](reviewer-agent.md) | SSDLC review phase; pre-merge gate alongside human code-owners | Produce structured review of code changes against repository conventions, test coverage, and security policy. | Engineering Productivity |
| `planner-agent` | [`planner-agent.md`](planner-agent.md) | Engineering planning ceremonies (refinement, sprint planning); epic/story decomposition | Decompose engineering tasks into sequenced sub-tasks scoped to other agents in the catalog. | Engineering Productivity |
| `release-agent` | [`release-agent.md`](release-agent.md) | Release management; change windows; canary / blue-green rollouts | Orchestrate release-cut activities under CI/CD policy: changelog synthesis, version selection, release-note drafting, gate verification. | Release Engineering |

## IT Infrastructure & Operations (ITIO) (3)

Anchored to ITIL 4 change / incident / problem management and SRE practices (SLI / SLO / error budgets / blameless postmortems).

| Agent | File | Process anchor | Mission summary | Owner |
|---|---|---|---|---|
| `sre-agent` | [`sre-agent.md`](sre-agent.md) | SLI / SLO / error budget management; toil reduction; infrastructure-as-code authoring | Capacity analysis, IaC drift detection, deployment topology synthesis, infrastructure change drafting. | SRE (under IT Operations) |
| `change-impact-agent` | [`change-impact-agent.md`](change-impact-agent.md) | ITIL change management; CAB review preparation; blast-radius analysis | Pre-deployment impact analysis: blast radius, downstream dependency map, rollback feasibility. | SRE (cross-cutting with Release Engineering) |
| `incident-triage-agent` | [`incident-triage-agent.md`](incident-triage-agent.md) | ITIL incident management; SEV1–SEV4 classification; MTTA / MTTR targets; runbook execution | Triage active incidents: log correlation, hypothesis ranking, runbook surfacing, severity classification recommendation. | IT Operations (NOC / Service Desk Tier 2) |

## Cybersecurity & Compliance (CyberOps) (3)

Anchored to SSDLC checkpoints (threat modeling, SAST / DAST / SCA), vulnerability management lifecycle (CVE → CVSS → patch SLA → exception), and compliance evidence collection mapped to control frameworks.

| Agent | File | Process anchor | Mission summary | Owner |
|---|---|---|---|---|
| `security-review-agent` | [`security-review-agent.md`](security-review-agent.md) | SSDLC security gate; architecture and change review; SAST / DAST / SCA finding triage | Security review of code, configuration, and infrastructure changes against the enterprise's policy and threat models. | Security Architecture |
| `vuln-triage-agent` | [`vuln-triage-agent.md`](vuln-triage-agent.md) | Vulnerability management lifecycle; CVE intake, CVSS scoring, patch SLA tracking, exception handling | Vulnerability triage: CVE intake, asset mapping, severity assessment, patch prioritization, exception drafting. | Vulnerability Management (under CISO) |
| `compliance-evidence-agent` | [`compliance-evidence-agent.md`](compliance-evidence-agent.md) | Compliance evidence collection; control framework mapping; audit-window evidence packaging | Collect, organize, and submit compliance evidence from the audit federation bus into `[ENTERPRISE: GRC platform]`; surface gaps against active control frameworks. | GRC |

## Cross-cutting friction surface

The catalog's three-domain decomposition is operationally real because four agents work across domain boundaries:

- `reviewer-agent` consumes `coder-agent` outputs and emits findings consumed by `security-review-agent` (when matching trigger patterns) and by human reviewers.
- `security-review-agent` consumes outputs from `coder-agent` (code), `sre-agent` (IaC, infrastructure config), and `release-agent` (release artifacts) at the SSDLC security gate.
- `change-impact-agent` consumes outputs from `sre-agent` (infrastructure changes) and `release-agent` (application releases) before deployment; emits findings consumed by CAB-equivalent change review.
- `compliance-evidence-agent` consumes the federation audit bus that all agents emit to; its findings feed back to all three domain owners.

Without these cross-cutting agents, the domain decomposition becomes nominal — agents drift into siloed automation that the federation bus cannot reconcile.

## Catalog discipline

**Additions** to this catalog require an agent contract review (Modus Primus §9.5) before the contract may be registered in the Secundus capability registry. Inheritance correctness and operational coherence are both evaluated; failure on either prevents approval. The full review process is in `[ENTERPRISE: agent contract review procedure]`.

**Retirements** require a documented successor (or explicit declaration that no successor is needed) and an audit-trail transfer plan per the post-retirement obligations in the agent contract's lifecycle section. Audit retention obligations survive the agent's retirement.

**Revisions** to existing contracts go through the same review gate. Permission scope changes (expanding `means` authorization, broadening data scope) require justification documented in the revision proposal; narrowing scope or strengthening constraints does not require justification but does require review for downstream coherence.

## Mission inheritance

Every agent in this catalog inherits its mission scope as a strict subset of `meta-harness/mission.md`. No agent's mission scope expands the enclave's mission; expansion requires a Secundus-level mission revision, which is out of scope for a Tertius contract review.

## Modus Primus catalog mapping

The Modus Primus v1.1 spec enumerates a generic agent catalog at B.6.1. This enclave's mapping:

| Modus Primus B.6.1 entry | This enclave |
|---|---|
| B.6.1.2 `researcher-agent` | Not used (mission-scope mismatch — research is out of scope for the three-domain enclave) |
| B.6.1.3 `coder-agent` | Used; `agents/coder-agent.md` |
| B.6.1.4 `reviewer-agent` | Used; `agents/reviewer-agent.md` |
| B.6.1.5 `planner-agent` | Used; `agents/planner-agent.md` |
| B.6.1.6 `analyst-agent` | Specialized to `incident-triage-agent` for ITIO scope |
| B.6.1.7 `mission-agent` | Not used (mission systems out of scope) |
| B.6.1.8 `governance-agent` | Not used in v1.1 (manual governance work; candidate for v1.2 baseline) |
| B.6.1.9 `retrieval-agent` | Absorbed into per-agent retrieval scopes |
| B.6.1.10 `synthesis-agent` | Absorbed into `planner-agent` cross-agent orchestration |
| _domain-specific extensions_ | `release-agent`, `sre-agent`, `change-impact-agent`, `security-review-agent`, `vuln-triage-agent`, `compliance-evidence-agent` |

The catalog is 10 agents in this enclave. The Modus Primus B.6.1 enumeration is generic; the per-enclave realization specializes (`analyst-agent` → `incident-triage-agent`), absorbs (`retrieval-agent` into per-agent scopes), and extends (six domain-specific agents) per the spec's design intent.
