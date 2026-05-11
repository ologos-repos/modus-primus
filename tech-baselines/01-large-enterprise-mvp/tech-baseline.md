# Tech Baseline — 01-large-enterprise-mvp

**WBS reference:** Modus Primus v1.1 Appendix B
**Template:** Modus Primus v1.1 Appendix D
**Enclave:** Modus Secundus 01 (Unclassified Enterprise GovCloud-equivalent)
**Effective date:** `[ENTERPRISE: effective date]`
**Last review:** `[ENTERPRISE: last review date]`
**Owner:** `[ENTERPRISE: per-enclave tech baseline owner — named role within the Governance & Strategy directorate]`

## Maturity legend

- **M** — Mature: real artifact under change control, governed, integrated with downstream enforcement.
- **P** — Partial: artifact exists but coverage incomplete, integration partial, or governance not fully established.
- **A** — Aspirational: slot is named in the tech baseline but not yet filled. Paper-only.

A tech baseline dominated by **A** entries indicates an early-stage instance; a tech baseline with mostly **M** entries and some **A** in the runtime-assurance layer is typical because runtime-assurance commercial products lag. This MVP baseline reflects that distribution.

## B.2 System Orientation

| WBS | Fulfillment | Owner | Status | Open dependencies / risks |
|---|---|---|---|---|
| B.2.1 `mode.md` | `meta-harness/mode.md` | Chief AI Architect | M | None |

## B.3 Meta-Harness Layer

| WBS | Fulfillment | Owner | Status | Open dependencies / risks |
|---|---|---|---|---|
| B.3.1 `mind.md` | `meta-harness/mind.md` | Chief AI Architect | M | None |
| B.3.2 `morals.md` | `meta-harness/morals.md` | CISO Organization (Governance & Compliance, delegated to GRC) | M | Pending alignment with `[ENTERPRISE: regulatory regime]` annual review |
| B.3.3 `mission.md` | `meta-harness/mission.md` | VP Engineering + VP IT Operations + CISO (joint ownership for three-domain enclave) | M | None |
| B.3.4 `memory.md` | `meta-harness/memory.md` | Data Governance | P | Retention classification mapping incomplete for L4 sensitivity tier; data-residency tagging in progress |
| B.3.5 `means.md` | `meta-harness/means.md` | Capability Owners aggregate (Means Owner role under Governance & Strategy) | P | Two means awaiting formal election review; see §9.7 cadence below |

## B.4 Cognitive Engine Layer

This baseline realizes **Scenario 2** (self-hosted open-source / open-weights). All B.4 entries reflect enterprise-hosted substrate rather than vendor-API substrate. A Scenario 1 sibling baseline would substitute commercial-cloud-hosted equivalents at this layer without changing any other WBS layer.

| WBS | Fulfillment | Owner | Status | Open dependencies / risks |
|---|---|---|---|---|
| B.4.1.1 Foundation models | Primary: `[ENTERPRISE: open-weights instruction model class — typically a current-generation large open-weights model in the 70B–400B parameter range]`. Secondary: `[ENTERPRISE: secondary open-weights model for redundancy and routing diversity]`. Both hosted on enterprise GPU infrastructure | Cognitive Plane Owner (Platform Engineering) | M | Model lifecycle (release, deprecation) managed by Cognitive Plane Owner per `[ENTERPRISE: model registry policy]` |
| B.4.1.2 Specialized models | Code-specialized open-weights model (`[ENTERPRISE: code model class — typically a current-generation open-weights code model]`); embedding model for retrieval (`[ENTERPRISE: open-weights embedding model]`); security-tuned model for SOC use cases (`[ENTERPRISE: SOC-tuned variant — typically fine-tuned from a base model on internal SOC traces]`) | Cognitive Plane Owner | M | None |
| B.4.1.3 Multi-model routing | Capability-registry-bound; routing per agent contract; routing engine inside the enterprise inference platform | Cognitive Plane Owner | M | Routing telemetry feeding observability (B.10) |
| B.4.1.4 Inference management | `[ENTERPRISE: in-house inference platform — typically vLLM, TGI, NVIDIA Triton, RayServe, or equivalent, fronted by an enterprise-grade gateway]` running on `[ENTERPRISE: enclave-controlled GPU fleet]` | Platform Engineering | M | Capacity managed by SRE under SLO discipline |
| B.4.1.5 Context windows | Per-substrate maxima per chosen model class; truncation policy in `meta-harness/memory.md` | Cognitive Plane Owner | M | None |
| B.4.1.6 Embedding systems | `[ENTERPRISE: enterprise-hosted vector store — typically a self-hosted vector database deployed within the enclave]`; embeddings produced by B.4.1.2 embedding model | Platform Engineering | M | None |
| B.4.1.7 Fine-tuned variants | Fine-tuning pipeline operated in-house against enterprise data sets; variants registered through means-election review (§9.7) before becoming elected substrates | Cognitive Plane Owner | P | Tuning pipeline operational for the SOC-tuned variant; broader pipeline coverage in progress |
| B.4.1.8 Reasoning modes | Inherited from `mind.md` reasoning policy; per-model reasoning-mode mapping documented in the substrate adapter | Cognitive Plane Owner | M | None |
| B.4.1.9 Latency optimization | Per-agent SLO targets in contracts; inference-platform-level optimizations (batching, paged attention, speculative decoding) tuned per workload class | Platform Engineering | P | SLOs declared; instrumentation under construction; speculative decoding gated on platform readiness |
| B.4.1.10 Confidence handling | Inherited from `mind.md` uncertainty policy; substrate-specific signals (log-prob distributions, refusal patterns) surfaced through the adapter into governance-plane primitives per PAHA §11 second option | Cognitive Plane Owner | M | None |

## B.5 Orchestration Layer

| WBS | Fulfillment | Owner | Status | Open dependencies / risks |
|---|---|---|---|---|
| B.5.1.1 `orchestrator.md` | `orchestration/orchestrator.md` | Orchestration Owner (Platform Engineering) | M | None |
| B.5.1.2 Routing | Capability-registry-driven; declared in orchestrator | Orchestration Owner | M | None |
| B.5.1.3 Delegation | Per Modus tier hierarchy (§4.3) | Orchestration Owner | M | None |
| B.5.1.4 Sequencing | Per-task; agent-contract-bounded | Orchestration Owner | M | None |
| B.5.1.5 Coordination | Multi-agent patterns documented per scenario class (change-with-security-review, incident-with-compliance-evidence, etc.) | Orchestration Owner | P | Coordination catalog incomplete for cross-domain scenarios |
| B.5.1.6 Arbitration | Conflict resolution to Secundus orchestrator | Orchestration Owner | M | None |
| B.5.1.7 Load balancing | `[ENTERPRISE: orchestration platform]` native | Platform Engineering | M | None |
| B.5.1.8 Task decomposition | Agent-contract-bounded; declared in `mission.md` | Orchestration Owner | M | None |
| B.5.1.9 Execution planning | Per-invocation; bounded by execution-policy | Orchestration Owner | M | None |
| B.5.1.10 Recovery handling | Idempotency + rollback per agent contract | Orchestration Owner + Agent Owners | P | Rollback procedures partial for IaC-modifying agents; full coverage gated on `change-impact-agent` maturity |

## B.6 Agent Layer

### B.6.1 Catalog

| WBS | Fulfillment | Domain | Owner | Status |
|---|---|---|---|---|
| B.6.1.1 `agents.md` | `agents/agents.md` | (catalog) | Agent Owners aggregate | M |
| B.6.1.3 `coder-agent.md` | `agents/coder-agent.md` | DevOps | Engineering Productivity | M |
| B.6.1.4 `reviewer-agent.md` | `agents/reviewer-agent.md` | DevOps | Engineering Productivity | M |
| B.6.1.5 `planner-agent.md` | `agents/planner-agent.md` | DevOps | Engineering Productivity | M |
| _ext_ `release-agent.md` | `agents/release-agent.md` | DevOps | Release Engineering | M |
| _ext_ `sre-agent.md` | `agents/sre-agent.md` | ITIO | SRE (under IT Operations) | M |
| _ext_ `change-impact-agent.md` | `agents/change-impact-agent.md` | ITIO | SRE (cross-cutting with Release Engineering) | M |
| B.6.1.6 `incident-triage-agent.md` | `agents/incident-triage-agent.md` | ITIO | IT Operations (NOC / Service Desk Tier 2) | M |
| _ext_ `security-review-agent.md` | `agents/security-review-agent.md` | CyberOps | Security Architecture | M |
| _ext_ `vuln-triage-agent.md` | `agents/vuln-triage-agent.md` | CyberOps | Vulnerability Management (under CISO) | M |
| _ext_ `compliance-evidence-agent.md` | `agents/compliance-evidence-agent.md` | CyberOps | GRC | P |

### B.6.1 Catalog entries not used in this enclave

| WBS | Reason |
|---|---|
| B.6.1.2 `researcher-agent.md` | Out of scope for the three-domain enclave |
| B.6.1.7 `mission-agent.md` | Mission systems are out of scope for this enclave |
| B.6.1.8 `governance-agent.md` | Manual governance work remains; election to elevate to an agent contract is on the v1.2 baseline candidate list |
| B.6.1.9 `retrieval-agent.md` | Absorbed into per-agent retrieval scopes (`coder`, `reviewer`, `incident-triage`) |
| B.6.1.10 `synthesis-agent.md` | Cross-agent synthesis covered by `planner-agent` orchestration patterns |

### B.6.2 Agent mechanics

| WBS | Fulfillment | Owner | Status |
|---|---|---|---|
| B.6.2.1 Lifecycle | Per `execution-runtime.md` + per-agent contract lifecycle sections | Platform Engineering | M |
| B.6.2.2 Identity | Service-identity-per-agent; rotation per `[ENTERPRISE: service identity rotation policy]` | IAM | M |
| B.6.2.3 Memory scope | Per-agent in contract; enforced by `memory.md` retention | Data Governance | M |
| B.6.2.4 Multi-agent coordination | Per orchestration patterns (B.5.1.5) | Orchestration Owner | P |
| B.6.2.5 Swarm execution | Limited use; `incident-triage-agent` and `coder-agent` Quintus patterns only | Per agent | M |

### B.6.3 Agent contract format

| WBS | Fulfillment | Owner | Status |
|---|---|---|---|
| B.6.3 `agent-contract.md` format | Per Modus Primus Appendix E | Agent Owners | M |

## B.7 Mechanism Layer

| WBS | Fulfillment | Owner | Status | Open dependencies / risks |
|---|---|---|---|---|
| B.7.1.1 API integrations | `mechanisms/tools.md` API catalog | Mechanism Layer Owner (Platform Engineering) | P | API inventory ~80% complete; cross-org APIs (CMDB, ticketing, SIEM, GRC) still being onboarded |
| B.7.1.2 Search systems | `[ENTERPRISE: enterprise search platform]` + repo-scoped code search + SIEM search for SOC use cases | Mechanism Layer Owner | M | None |
| B.7.1.3 File systems | Enterprise repositories + `[ENTERPRISE: artifact stores]` + audit evidence archives | Mechanism Layer Owner | M | None |
| B.7.1.4 Code execution environments | Sandboxed per execution-policy; isolated for security-review's SAST/DAST tooling | Platform Engineering | M | None |
| B.7.1.5 Communications channels | Restricted to enclave-internal `[ENTERPRISE: chat / ticketing / paging platforms]` for v1.1 | Mechanism Layer Owner | M | None |
| B.7.1.6 Data analysis pipelines | `[ENTERPRISE: data platform]`; SIEM analytics for CyberOps | Data Platform | M | None |
| B.7.1.7 Scheduling systems | `[ENTERPRISE: scheduler — typically the enterprise's job orchestration platform]`; on-call rotation integration for ITIO | Platform Engineering + IT Operations | M | None |
| B.7.1.8 Visualization systems | Dashboards in `[ENTERPRISE: observability platform]`; GRC dashboards for compliance | Platform Engineering + GRC | M | None |
| B.7.1.9 Simulation systems | None in this enclave | n/a | n/a | — |
| B.7.1.10 Automation pipelines | CI/CD platform; IaC platform; vulnerability scan pipelines; compliance evidence collection pipelines | Platform Engineering + Release Engineering + Vulnerability Management | M | None |

## B.8 Execution Governance Layer

| WBS | Fulfillment | Owner | Status | Open dependencies / risks |
|---|---|---|---|---|
| B.8.1 `execution-policy.md` | `execution-governance/execution-policy.md` | Governance & Strategy (joint with CISO Org) | M | None |
| B.8.2 `execution-runtime.md` | `execution-governance/execution-runtime.md` | Platform Engineering | P | Pre-action validation gates partial for IaC-modifying actions; emergency-change bypass procedure under review |

## B.9 Federated Architecture Layer

| WBS | Fulfillment | Owner | Status |
|---|---|---|---|
| B.9.1 Modus Primus | `[ENTERPRISE: enterprise-level Primus repository / authority]` | Chief AI Architect (Primus authority) | M |
| B.9.2 Modus Secundus 01 | This enclave; defined by this tech baseline | VP Engineering + VP IT Ops + CISO (joint) | M |
| B.9.3 Modus Tertius | 10 agents enumerated in B.6.1 | Agent Owners (per domain org) | M |
| B.9.4 Modus Quartus | Per-invocation, tool-bound; declared in each agent contract | Per agent | M |
| B.9.5 Modus Quintus | Parallel patterns used by `coder-agent` (multi-file analysis), `incident-triage-agent` (parallel log correlation), and `compliance-evidence-agent` (parallel control-set evidence collection) | Per agent | M |

## B.10 Observability and Assurance Layer

| WBS | Fulfillment | Owner | Status | Open dependencies / risks |
|---|---|---|---|---|
| B.10.1.1 Telemetry | `[ENTERPRISE: observability platform]` | Platform Engineering | M | None |
| B.10.1.2 Auditability | Audit bus emitting to `[ENTERPRISE: audit aggregation / SIEM]` per federation schema | Platform Engineering | M | Schema conformance verified annually |
| B.10.1.3 Traceability | OpenTelemetry-equivalent spans across agent invocations | Platform Engineering | M | None |
| B.10.1.4 Compliance artifact collection | Tied to `[ENTERPRISE: GRC platform]`; `compliance-evidence-agent` is the primary consumer of this signal | GRC | P | GRC platform integration in progress |
| B.10.1.5 Behavioral analytics | Per-agent behavioral baselines | Runtime Assurance Owner | P | Baselines under calibration for `compliance-evidence` and `vuln-triage` |
| B.10.2.1 Drift detection | `[ENTERPRISE: drift detection capability]` | Runtime Assurance Owner | A | Commercial product maturity gap; in-house prototype under evaluation |
| B.10.2.2 Mission coherence monitoring | In-house instrument; signals tied to mission objectives in `mission.md` | Runtime Assurance Owner | A | Instrument design complete; calibration in progress |
| B.10.2.3 Policy deviation detection | Pre-action validation in `execution-runtime.md`; real-time post-validation in flight | Runtime Assurance Owner + Platform Engineering | P | Pre-action complete; real-time partial |
| B.10.2.4 Explainability surfacing | Per-decision rationale capture in audit records; expanded scope for CyberOps audit needs | Runtime Assurance Owner | P | Rationale capture for tool-using actions complete; pure-reasoning rationale partial |

## Real-world process anchors

Each domain anchor maps to recognized enterprise IT practice. Agents in each domain inherit process expectations:

| Domain | Anchors |
|---|---|
| DevOps | Trunk-based development; PR gating with code-owners; CI/CD with mandatory quality gates; SSDLC checkpoints; release management (blue/green, canary, feature flags); SLO-driven release readiness |
| ITIO | ITIL 4 — change management with CAB review; incident management with SEV1–SEV4 classification, MTTA / MTTR targets, post-incident review; problem management; capacity management; SRE — SLI / SLO / error-budget discipline, blameless postmortems |
| CyberOps | SSDLC — threat modeling, SAST / DAST / SCA gates; vulnerability management — CVE intake, CVSS scoring, severity-driven patch SLAs, exception management; compliance — control framework mapping (NIST 800-53, ISO 27001, SOC 2, `[ENTERPRISE: applicable industry framework]`), evidence collection cycles, audit-window scoping |

These anchors are reflected in each agent's contract under §1 (Identity → Role) and §4 (Escalation triggers), so the agents operate within recognized enterprise process patterns rather than inventing their own.

## Gap summary

The aspirational entries cluster in two places:

1. **Runtime assurance (B.10.2.1, B.10.2.2).** Expected per Modus Primus §5.4. The runtime-assurance commercial-maturity survey (companion document; v1.2 Candidate 4, [PR #4](https://github.com/ologos-repos/modus-primus/pull/4) merged) is the spec-side artifact addressing this gap; tech-baselines will cite the survey edition once published.
2. **Governance-tier agents (B.6.1.8 not in this baseline).** Governance work is currently manual; agent contracts for governance automation are on the v1.2 baseline candidate list.

Partial entries cluster around bootstrap completion: API inventory across IT silos (CMDB, ticketing, SIEM, GRC), retention classification mapping, real-time policy deviation, behavioral baselines for the newer agents, recovery handling for IaC-modifying agents, GRC platform integration. None are blockers for operational deployment; all are tracked under the enclave's continuous-improvement cadence (`[ENTERPRISE: quarterly tech baseline review per §9.2]`).

## Means election cadence

Two means in `meta-harness/means.md` are awaiting formal election review under §9.7:

- `B.3.5.6 Communications channels` — proposed extension to include cross-enclave coordination via `[ENTERPRISE: cross-enclave messaging surface]`; pending federation schema review.
- `B.3.5.7 Media generation` — proposed addition for incident post-mortem visualization and compliance evidence packaging; pending means-election review against existing mechanism inventory.

Both elections are documented in the means-election review queue per §9.7 entry criteria.
