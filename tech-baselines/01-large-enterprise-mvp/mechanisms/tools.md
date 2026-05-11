# tools.md — Mechanism Layer Inventory

**Modus Primus v1.1 reference:** B.7
**Owner:** Mechanism Layer Owner (Platform Engineering)
**Layer:** Operational inventory. Catalogs what is operationally available. Per the means/mechanisms principle (Modus Primus Appendix C), entries here become *part of the system's disposition* only when elected as means in `meta-harness/means.md` (B.3.5). Unelected mechanisms remain inventory.

## Scenario context

This baseline realizes **Scenario 2** (self-hosted open-weights). Mechanism entries below reflect that scenario; a Scenario 1 sibling baseline would substitute commercial-cloud-hosted equivalents at the cognitive substrate and inference platform entries without changing any other mechanism layer entry.

## B.7.1.1 API integrations

Catalog of API integrations available in the enclave's operational plane. Each entry is a mechanism; per-agent invocation authority is granted in agent contracts.

| API class | Representative platform / interface | Used by |
|---|---|---|
| Source control | `[ENTERPRISE: Git platform — typically GitLab Enterprise, GitHub Enterprise, Bitbucket Data Center, or equivalent]` | DevOps agents |
| CI/CD | `[ENTERPRISE: CI/CD platform]` | `release-agent`, `reviewer-agent` (read-only) |
| IaC platforms | `[ENTERPRISE: IaC platform — typically Terraform Enterprise, Ansible Automation Platform, Pulumi, or equivalent]` | `sre-agent`, `change-impact-agent` (read-only) |
| Cloud control planes / Kubernetes | `[ENTERPRISE: enclave cloud control plane APIs and / or Kubernetes APIs]` | `sre-agent`, `change-impact-agent` (read-only) |
| CMDB | `[ENTERPRISE: CMDB — typically ServiceNow CMDB, BMC Helix, or equivalent]` | `sre-agent`, `change-impact-agent`, `incident-triage-agent`, `vuln-triage-agent` (read-only) |
| ITSM | `[ENTERPRISE: ITSM platform — typically ServiceNow, BMC Helix, Cherwell, or equivalent]` | `release-agent`, `change-impact-agent`, `incident-triage-agent` (attachment-write only) |
| Observability | `[ENTERPRISE: observability platform — typically Datadog, Splunk, Dynatrace, Grafana Enterprise, or equivalent]` | `sre-agent`, `incident-triage-agent`, `release-agent` (read-only) |
| SIEM | `[ENTERPRISE: SIEM platform — typically Splunk Enterprise Security, Microsoft Sentinel, Chronicle, or equivalent]` | `security-review-agent`, `incident-triage-agent` (read-only for incident triage) |
| Vulnerability management | `[ENTERPRISE: VM platform — typically Tenable, Qualys, Rapid7, or equivalent]` | `vuln-triage-agent` (read for scanning context; draft-write for triage records) |
| CVE / threat intelligence feeds | `[ENTERPRISE: TI platform — typically commercial threat intel feeds plus open-source CVE feeds (NVD, MITRE)]` | `vuln-triage-agent`, `security-review-agent` (read-only) |
| GRC | `[ENTERPRISE: GRC platform — typically RSA Archer, ServiceNow GRC, OneTrust, MetricStream, or equivalent]` | `compliance-evidence-agent` (read for control library; write for evidence submission) |
| Code scanners | `[ENTERPRISE: SAST / DAST / SCA stack — typically a mix of Veracode, Snyk, Checkmarx, GitLab security scanners, or equivalent]` | `security-review-agent`, `reviewer-agent` (sandboxed execution) |
| Secret detection | `[ENTERPRISE: secret detection — typically GitGuardian, TruffleHog, or equivalent integrated into the Git platform]` | `coder-agent` (read findings only — not the secret values), `security-review-agent` |
| On-call / paging | `[ENTERPRISE: paging platform — typically PagerDuty, Opsgenie, or equivalent]` | `incident-triage-agent` (recommendation-emit only) |
| Audit federation bus | `[ENTERPRISE: enclave audit aggregation surface, typically a stream + persistence pair]` | All agents (write per `execution-runtime.md` B.8.2.10); `compliance-evidence-agent` (read) |

API inventory is `[ENTERPRISE: ~80% complete]` per `tech-baseline.md` B.7.1.1 status.

## B.7.1.2 Search systems

| Search class | Representative platform | Used by |
|---|---|---|
| Enterprise search (cross-platform metadata search) | `[ENTERPRISE: enterprise search platform]` | All agents (read-only) |
| Repo-scoped code search | Native Git platform code search | DevOps and CyberOps agents |
| SIEM search | (per B.7.1.1 SIEM) | `incident-triage-agent`, `security-review-agent` |
| Runbook library search | `[ENTERPRISE: runbook library — typically a structured Confluence space, GitOps runbook repo, or a dedicated runbook platform]` | `incident-triage-agent`, `sre-agent` |
| Policy library search | `[ENTERPRISE: security policy library — typically a structured documentation system under CISO ownership]` | `security-review-agent`, `compliance-evidence-agent` |
| Threat model search | `[ENTERPRISE: threat model repository — typically a Git-managed repo of structured threat models per service]` | `security-review-agent` |

## B.7.1.3 File systems

| Filesystem class | Scope | Used by |
|---|---|---|
| Source repositories | `[ENTERPRISE: source repo storage]` | DevOps agents (read), CyberOps agents (read for review) |
| IaC repositories | Tag `production-iac` repos within source repo storage | `sre-agent`, `change-impact-agent` |
| Artifact registries | `[ENTERPRISE: artifact registry — typically Artifactory, Nexus, GitHub Packages, or equivalent]` | `release-agent`, `security-review-agent` |
| Audit evidence archive | `[ENTERPRISE: long-term audit retention store]` | `compliance-evidence-agent` (read for historical correlation) |

## B.7.1.4 Code execution environments

| Environment class | Implementation | Used by |
|---|---|---|
| Sandbox runtime | `[ENTERPRISE: sandboxed container or microVM runtime — typically a hardened K8s namespace, gVisor, Firecracker, or equivalent, with default-deny network egress]` | All agents performing Class C execution per `execution-policy.md` |
| Test execution | Sandbox runtime configured for test framework execution per language family | `coder-agent`, `reviewer-agent` (read-only verification) |
| Static analysis execution | Sandbox runtime configured for linting and type-checking | `coder-agent`, `reviewer-agent` |
| Scanner execution | Sandbox runtime configured with SAST / DAST / SCA tooling per B.7.1.1 | `security-review-agent` |
| Dry-run IaC execution | Sandbox runtime with read-only or non-production environment access | `sre-agent` |

## B.7.1.5 Communications channels

| Channel | Scope | Used by |
|---|---|---|
| Pull-request comments and reviews | Per source-platform native APIs | DevOps and CyberOps agents (per contract) |
| Change-record attachments | Per ITSM platform native API | `change-impact-agent`, `release-agent` |
| Incident-record attachments | Per ITSM platform native API | `incident-triage-agent` |
| Vulnerability record drafts | Per VM platform native API | `vuln-triage-agent` |
| Federation audit bus emission | Per audit aggregation surface | All agents |
| `[ENTERPRISE: chat / collaboration platform]` notifications | Restricted to non-action notifications | All agents (out-of-band coordination only, not action authority) |

## B.7.1.6 Data analysis pipelines

| Pipeline class | Implementation | Used by |
|---|---|---|
| Service log analytics | `[ENTERPRISE: log analytics — typically integrated with observability platform or SIEM]` | `incident-triage-agent`, `sre-agent` |
| Security analytics | `[ENTERPRISE: SIEM analytics]` | `security-review-agent`, `incident-triage-agent` |
| Compliance analytics | `[ENTERPRISE: GRC analytics surface]` | `compliance-evidence-agent` |
| Vulnerability analytics | `[ENTERPRISE: VM platform analytics]` | `vuln-triage-agent` |

## B.7.1.7 Scheduling systems

| Scheduler class | Implementation | Used by |
|---|---|---|
| Job orchestration | `[ENTERPRISE: job scheduler — typically the enterprise's CI/CD platform's scheduled-job capability or a dedicated orchestration platform]` | `compliance-evidence-agent` (scheduled audit-window collection), `sre-agent` (scheduled drift scans), `vuln-triage-agent` (scheduled CVE feed intake) |
| On-call rotation | `[ENTERPRISE: on-call system, per B.7.1.1]` | `incident-triage-agent` (read-only for paging recommendation) |
| Change calendar | `[ENTERPRISE: change calendar source — typically integrated into ITSM]` | `release-agent`, `change-impact-agent` (read-only) |

## B.7.1.8 Visualization systems

| Visualization class | Implementation | Used by |
|---|---|---|
| Operational dashboards | `[ENTERPRISE: observability platform native dashboards]` | (read context, not write) |
| GRC dashboards | `[ENTERPRISE: GRC platform native dashboards]` | (read context for audit-window state) |
| Vulnerability dashboards | `[ENTERPRISE: VM platform native dashboards]` | (read context) |

(Agents typically do not write to dashboards; dashboards are downstream of the audit federation bus and observability emission.)

## B.7.1.9 Simulation systems

None in this enclave.

## B.7.1.10 Automation pipelines

| Pipeline class | Implementation | Used by |
|---|---|---|
| CI/CD pipelines | (per B.7.1.1 CI/CD) | `release-agent` (read state, propose changes), `reviewer-agent` (read state) |
| IaC pipelines | (per B.7.1.1 IaC platforms) | `sre-agent` (propose, dry-run), `change-impact-agent` (read state) |
| Vulnerability scan pipelines | (per B.7.1.1 VM platform) | `vuln-triage-agent` (read results) |
| Compliance evidence pipelines | Scheduled jobs invoking `compliance-evidence-agent` per B.7.1.7 | `compliance-evidence-agent` itself; orchestrated by audit-window scheduler |

## Cognitive substrate adapters (Scenario 2)

Although Modus Primus places substrate at B.4 (Cognitive Engine layer) rather than B.7 (mechanism layer), the substrate adapters that bridge the cognitive plane to operationally-available substrates are mechanism-layer artifacts. Catalog for Scenario 2:

| Adapter class | Representative implementation | Used by |
|---|---|---|
| Primary instruction model adapter | `[ENTERPRISE: large open-weights instruction model class hosted on the in-house inference platform]` — adapter handles request shaping, response parsing, refusal-pattern normalization, log-prob exposure | All agents whose contracts authorize instruction-class reasoning |
| Code-specialized model adapter | `[ENTERPRISE: open-weights code-specialized model class]` | `coder-agent`, `reviewer-agent` |
| Embedding model adapter | `[ENTERPRISE: open-weights embedding model class]` paired with `[ENTERPRISE: vector store]` | Retrieval pathways across agents |
| Inference platform interface | `[ENTERPRISE: in-house inference platform — vLLM / TGI / Triton / etc.]` running on `[ENTERPRISE: GPU fleet]` | All adapter calls |

A Scenario 1 sibling baseline would substitute commercial-API adapters at each row (e.g., a primary commercial frontier-model API, a vendor-native code assistant adapter, a vendor embedding API). Per PAHA §11, adapter substitution preserves the agent contracts; only the adapter implementation changes.

## Substrate selection policy

Per-agent substrate selection is bound at the capability registry. The cognitive plane owner maintains a substrate-election registry indicating, for each agent, which substrate adapter handles its reasoning. Selection criteria (typical):

- Primary instruction adapter for general reasoning tasks
- Code-specialized adapter for code-generation and code-analysis tasks
- Embedding adapter for retrieval-augmented tasks
- Multi-adapter routing within an agent's invocation tree per per-agent contract

Substrate substitution is governed by Modus Primus §7.5 (substrate substitution re-verification) and §9.6 (substrate substitution review).

---

## Concrete reference artifacts

The baseline ships two concrete operational consoles as sibling reference kits under [`consoles/`](../consoles/). Adopters fork these as starting points; each kit is fully `[ENTERPRISE:]`-marker-driven and runs once markers are resolved.

| Artifact | Path | Realizes |
|---|---|---|
| **Chat console reference kit** | [`consoles/chat-console-reference/`](../consoles/chat-console-reference/) | Human-interaction surface for the enclave. aiohttp + JS frontend, ~9K LOC. Replaces the abstract "operational interaction console" mechanism with a concrete starting point. |
| **Agents console reference kit** | [`consoles/agents-console-reference/`](../consoles/agents-console-reference/) | Agent operations surface for the Tertius layer. aiohttp + aiosqlite + substrate-adapter runtime, ~10K LOC. Includes four substrate adapter classes (self-hosted inference, cognitive-engine-CLI, two vendor APIs) so adopters can run Scenario 1 / 2 / hybrid out of the box. Curated spec catalog demonstrates research / services / workflows / triggers / ops patterns. |

Each kit is structured in three layers:

- `src/` — sanitized source code
- `deploy/` — service template, `.env.example`, deployment README (systemd-user reference; container / orchestrator substitutions documented)
- `network/` — VPN / overlay / zero-trust adapter pattern reference (the kits take no opinion on private connectivity)

Both kits are v0.2 of the baseline. v1.0+ feature expansion (tier-specific consoles, R&D best-of-Claude harvest) is tracked in the source-project's console architecture roadmap (out of scope for this tech-baseline document).

---

## Mechanism layer discipline

Per the means/mechanisms principle (Modus Primus Appendix C):

- Mechanisms above are *operationally available*. They become part of the system's disposition only through purposive election in `meta-harness/means.md`.
- Mechanism introductions (new tool, new platform, new substrate variant) go through means-election review (Modus Primus §9.7) before being elected as means.
- Mechanism retirement may proceed independently of means election if the mechanism is not currently elected. Mechanisms currently elected as means require coordinated means-election retirement before mechanism retirement.

The mechanism inventory drifts as the enterprise tech landscape evolves. The means inventory drifts only through governance acts. This asymmetry is the discipline that prevents silent capability creep.

---

This file is read at orchestrator boot, by agents at invocation for capability discovery, and at per-enclave tech baseline review (Modus Primus §9.2). Revisions are governance acts requiring Mechanism Layer Owner approval; means-election impact of any revision is assessed per §9.7.
