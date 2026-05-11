# means.md — The System's Purposive Repertoire

**Modus Primus v1.1 reference:** B.3.5
**Owner:** Means Owner role (under Governance & Strategy), aggregating per-capability owners
**Layer:** Meta-harness purposive declaration

This file declares what the system *uses toward its mission within its morals*. It is a purposive declaration, not a mechanism catalog. Mechanisms operationally available to the system are inventoried in `mechanisms/tools.md` (B.7); means in this file are mechanisms purposively elected via the means-election review (Modus Primus §9.7). Mechanisms not elected as means are not part of the system's disposition even if they remain operationally available.

## B.3.5.1 Capability inventory

The means elected for this enclave, organized by domain-anchor service. Each entry is a purposive declaration that the named capability is used by one or more agents toward the enclave mission within the enclave morals.

### DevOps capabilities

- Source-code analysis (read, parse, semantic understanding)
- Code generation and refactoring (proposal generation only; no direct write)
- Pull-request authoring and commenting
- Test authoring and read-only test execution
- Static analysis (linting, type checking)
- Repository convention enforcement (advisory)
- Task decomposition and dependency mapping
- Release-candidate analysis and changelog synthesis

### ITIO capabilities

- Infrastructure-as-code analysis and proposal (proposal generation only; no direct deploy)
- IaC drift detection
- Capacity analysis and SLO conformance modeling
- Deployment topology synthesis
- Change-impact assessment (blast radius, dependency mapping, rollback feasibility)
- Incident log correlation and runbook surfacing
- Severity classification recommendation

### CyberOps capabilities

- Security-policy-based code and IaC analysis
- Threat-model-aligned review
- SAST / DAST / SCA scanner orchestration and finding triage
- CVE intake and contextualized CVSS scoring
- Enterprise asset impact mapping
- Compliance evidence collection and control framework mapping
- Audit-window evidence packaging
- Gap surfacing against active control frameworks

## B.3.5.2 Workflow capabilities

Read / write surface elected for agent participation:

- Read: source repositories, IaC repositories, CMDB, observability platform, change-management records, incident records, vulnerability records, CVE feeds, SCA / SAST / DAST scanner outputs, audit federation bus, control library, GRC platform (read-only)
- Comment / annotate: pull requests, change records, incident records, vulnerability records
- Propose / draft (emission, not commit): IaC changes, release proposals, decompositions, runbooks, impact assessments, exception requests, evidence packages, gap findings
- Attach: findings and assessments to change records, incident records, vulnerability records, evidence packages
- Status-check emission: pull-request status checks (advisory inputs to repository policy)

Explicitly not elected as means at this baseline:

- Write to production source-of-truth systems (deployed services, infrastructure, secret stores, identity stores)
- Approval / closure / attestation actions in change-management, incident, vulnerability, or compliance systems
- Direct paging (paging is a recommended-emit only; the paging system is the actor)
- Cross-enclave network egress without federation-layer authorization

## B.3.5.3 Automation permissions

Permitted automation:

- Capability-registry-driven agent invocation by the orchestrator
- Webhook-triggered invocation from PR, change, incident, CVE, and audit-window source systems
- Scheduled invocation for periodic activities (audit-window evidence packaging, vulnerability feed intake, drift scans)
- Quintus parallel-pattern invocation per declared agent contract

Not permitted as automation:

- Auto-approval, auto-merge, auto-close, auto-attest. These actions remain human-mediated.
- Cross-agent invocation outside declared invitation patterns (per `agents/agents.md`)
- Scope expansion through automation (mission expansion requires governance act)

## B.3.5.4 Retrieval systems

Declarative; tool integrations live in `mechanisms/tools.md`. Means elected:

- Repository code search
- Language-server query
- Dependency graph query
- CMDB query
- Observability query (metrics, logs, traces)
- Change-history query
- Incident-history query
- Vulnerability and CVE search
- Threat intelligence query
- Control library and evidence mapping query
- Audit federation bus query
- GRC platform query (read-only)

## B.3.5.5 Execution pathways

Declarative; orchestration mechanics live in `orchestration/orchestrator.md` (B.5). Means elected:

- Sandboxed test execution
- Sandboxed static analysis execution
- Sandboxed SAST / DAST / SCA execution
- Dry-run IaC operations in non-production environments
- Sandboxed scanner orchestration with result aggregation

All execution is sandboxed; production execution is not an elected means.

## B.3.5.6 Communications channels

- PR-platform comment and status-check emission
- Change-record attachment emission
- Incident-record attachment emission and paging-recommendation emission
- Vulnerability-record draft emission
- Audit federation bus emission
- GRC platform submission

**Awaiting election review:** Cross-enclave coordination channel for federation-aware Modus Secundus instances. Pending federation schema review per Modus Primus §9.4.

## B.3.5.7 Media generation

Currently restricted to text outputs (markdown findings, structured records, code, IaC, runbooks). Image, diagram, and video generation are not currently elected means.

**Awaiting election review:** Diagram generation for incident post-mortem visualization and compliance evidence packaging. Pending means-election review per §9.7.

## B.3.5.8 Analysis capabilities

The analytical methods declared in `mind.md` (B.3.1.2) — evidence-weighted ranking, constraint-satisfaction analysis, pattern-matching with explicit-pattern-citation, decomposition-with-dependency-tracking — are the elected analytical means. Other reasoning patterns available in the Cognitive Engine substrate are not elected and are out of scope for this enclave.

## B.3.5.9 Code execution authorization

- Sandboxed code execution authorized for: test runs (read-only against target), linting, type-checking, dry-run IaC, security scanner execution
- Sandboxed execution constraints (resource limits, time bounds, network restrictions) enforced by `execution-runtime.md` (B.8.2)
- No production code execution authorization

## B.3.5.10 Human interaction surfaces

- Pull-request comments and review threads
- Change-management record attachments
- Incident response timelines (as a recorded contributor, not as an active operator)
- Vulnerability record updates (draft only)
- GRC platform reviewer interface (read for analyst; write for evidence submission)
- `[ENTERPRISE: chat / collaboration platform]` for non-action notifications and threaded discussion (out-of-band coordination, not action authority)

## B.3.5.11 Capability inheritance rules

This Secundus means inheritance is constrained by the Modus Primus enterprise-level means per §4.2 (`Primus to Secundus`):

- Inheritance is one-way; Primus elections flow down, Secundus elections do not propagate up.
- Secundus may strengthen (narrow scope, add constraints) but not weaken Primus elections.
- Means added at this Secundus level that have no Primus parent are local-only and require enterprise-level review for cross-enclave adoption.

Per-agent means inheritance from this file follows the same rules (`Secundus to Tertius`).

## B.3.5.12 Capability availability matrix

Per-agent means availability is declared in each agent contract's §2 (means authorization). The matrix is the cross-product of agents in `agents/agents.md` and the capability entries in §B.3.5.1 through §B.3.5.10 above. Per the means/mechanisms discipline, the matrix is not a complete cross-product — each cell is either explicitly granted in an agent contract or implicitly denied (default-deny). Per-agent grants are the source of truth; this file is the enclave-scope aggregate.

---

**Means election cadence:** Per Modus Primus §9.7. Reviews are event-driven (new mechanism introduction, mission-scope change, agent contract revision) plus a periodic full-means audit at each per-enclave tech baseline review (§9.2). Periodic audits surface drift (mechanisms in use without election) and ensure unelected entries are reconciled.

**Pending election queue:** Two entries (B.3.5.6 cross-enclave coordination channel, B.3.5.7 media generation for diagrams) per `tech-baseline.md` §B.3 partial status.

---

This file is read at orchestration boot and informs per-agent means authorization. Revisions are governance acts requiring means-election review per Modus Primus §9.7.
