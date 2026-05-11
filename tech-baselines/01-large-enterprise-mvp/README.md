# Tech Baseline 01 — Large-Enterprise MVP

A populated Modus Primus instance for a hypothetical sovereignty-bounded large enterprise. First enclave, scoped to three enterprise IT functions: **Development (DevOps)**, **IT Infrastructure & Operations (ITIO)**, and **Cybersecurity & Compliance (CyberOps)**. Snapshot artifact for [PAHA Rev 2.2](https://doi.org/10.5281/zenodo.20112631) + [Modus Primus v1.1](https://doi.org/10.5281/zenodo.20113785).

## What this is

A reference instance showing how a large enterprise might populate the Modus Primus WBS for its first Modus Secundus deployment across the three IT functions that bear the heaviest AI-agent leverage. The instance is concrete enough to evaluate the spec against real artifacts and abstract enough to be portable across the qualified market (PAHA §14): regulated finance, defense IT, intelligence, healthcare. Vertical-specific decisions are marked with `[ENTERPRISE:]` placeholders following the spec's own convention.

It is not the canonical realization of Modus Primus. Many design choices below are defensible alternatives among several; the instance picks one for concreteness and flags the choice where it matters.

## What this is not

- **Not a runtime substrate.** This baseline declares artifacts and contracts; the runtime engine, observability stack, and integration platforms required to make it operational are out of scope and supplied per `[ENTERPRISE:]` markers.
- **Not vendor-prescriptive.** Tools and platforms are named only where one is genuinely representative; elsewhere, `[ENTERPRISE:]` markers preserve the enterprise's procurement authority.
- **Not authoritative.** Modus Primus v1.1 is the canonical specification. Where this baseline appears to contradict the spec, the spec wins; please file an issue.

## Persona

**Enterprise:** Large, regulated, multi-vendor AI footprint already in flight. Existing IAM (centralized), CMDB (in remediation), CISO org with real authority, EA governance function with veto power on architectural decisions. Operates one or more sovereignty-bounded enclaves whose classification, sovereignty, or partner-isolation constraints rule out cleared commercial cloud for substrate hosting (high-side classified, air-gapped, partner-program-isolated, data-residency-restricted, or equivalent). Cognitive substrate is procured and operated as enterprise infrastructure (Scenario 2 above), not as a vendor service.

**Functional ownership** for the three domain anchors maps to recognized large-enterprise org structures:

| Domain | Primary org | Reports to | Operates against |
|---|---|---|---|
| DevOps | Engineering Productivity / Developer Experience | CTO or VP Engineering | Source repositories, CI/CD pipelines, build systems, artifact registries |
| ITIO | IT Operations + Platform Engineering | CIO | Infrastructure-as-code, deployment platforms, monitoring stacks, ITSM (incidents, changes, problems) |
| CyberOps | CISO Organization + GRC | CISO (GRC may dual-report to Chief Risk / Compliance) | SOC tooling, vulnerability management, SIEM, GRC platforms, audit evidence systems |

**First enclave scope:** Internal-facing only. Chosen because (a) the three domains have high agent-leverage and bounded blast radius compared to mission systems, customer-facing AI, or board-decision support, (b) practitioners are technically sophisticated and tolerant of early-stage governance overhead, (c) repository, pipeline, observability, and ticketing integrations are well-understood and procurable.

**Out of scope for this enclave:** Mission systems, customer-facing AI surfaces, classified workloads, board-level decision support, HR and finance functions.

## Deployment scenarios

The baseline is model-agnostic by design. PAHA's substrate-adapter pattern (PAHA §11, Modus Primus §6.1) and the capability registry's binding semantics mean agents are authored against an adapter interface, not against a specific foundation model. Substrate substitution is a registry-binding operation, not an agent rewrite.

Two procurement scenarios are supported by the architectural pattern. The enclave picks one or operates a mix; the architectural commitments are identical in both cases.

| Scenario | Substrate procurement | Typical fit |
|---|---|---|
| 1 — Commercial cloud-hosted | Frontier-model APIs cleared for the enclave (e.g., a primary vendor and a redundant secondary); vendor-native code assistants permitted as operational-plane mechanisms distinct from the harness substrate | Enclaves whose sensitivity permits cleared commercial cloud (FedRAMP Moderate/High commercial offerings, regulated finance cloud, healthcare cloud); latency / throughput requirements met by hosted inference |
| 2 — Self-hosted open-source / open-weights | Open-weights foundation models hosted on enterprise GPU infrastructure via an in-house inference platform; adapter translates between harness-governed signals and the enterprise's inference endpoints | Enclaves with classification, sovereignty, or partner-isolation constraints preventing cleared commercial cloud; enclaves whose risk posture requires substrate observability that vendor-hosted inference does not provide |

### This baseline realizes Scenario 2

This tech baseline is the **Scenario 2** realization: self-hosted open-source / open-weights substrate on enterprise infrastructure. A separate baseline (likely `tech-baselines/02-...`) would realize Scenario 1 against the same WBS.

Why Scenario 2 here:

- The persona is a sovereignty-bounded enclave whose data classification, partner-isolation contract, or residency obligation prevents commercial-cloud-hosted inference. The enclave's substrate must be operated within the enterprise's accreditation boundary.
- Substrate observability — full visibility into prompt routing, inference traces, and refusal signals — is an architectural commitment in this enclave that vendor-hosted inference cannot deliver to the required depth.
- The cognitive-plane runtime is procured as enterprise infrastructure, governed by the same CMDB, change management, and asset lifecycle disciplines as other enterprise platforms, rather than as a vendor service.

The architectural pattern does not change. A Scenario 1 sibling baseline would have identical agent contracts, identical execution governance, identical V&V instruments — only B.4 entries and `mechanisms/tools.md` adapter implementations would differ.

### What this constrains in the rest of the baseline

- The B.4 Cognitive Engine entries in `tech-baseline.md` enumerate Scenario 2 specifics (open-weights model classes, in-house inference platforms, enterprise GPU infrastructure) with `[ENTERPRISE:]` markers preserved for the per-enclave product / version choices.
- Agent contracts (§2 Inheritance) bind to the capability-registry substrate adapter, not to a specific model name; the adapter implementation differs between scenarios but the contract is unchanged. Substrate substitution V&V (`§7.5`) applies uniformly.
- `mechanisms/tools.md` enumerates representative open-weights substrate-adapter implementations as election candidates; the enclave's actual elected adapters are recorded in the cognitive plane owner's per-enclave configuration.

## Domain anchors

### 1. Development (DevOps)

Source code and software-delivery activities across the engineering organization. Anchored to recognized DevOps practice: trunk-based development with PR gating, repository conventions enforced by code-owners and branch protection, CI/CD pipelines with mandatory quality gates, release management following blue/green or canary patterns per change-risk classification.

Representative agents (4): `coder-agent`, `reviewer-agent`, `planner-agent`, `release-agent`.

### 2. IT Infrastructure & Operations (ITIO)

Infrastructure lifecycle and service operations. Anchored to ITIL 4 practices: change management with CAB review for non-standard changes, incident management with severity-driven response (SEV1–SEV4) and MTTR/MTTA targets, problem management feeding root-cause analysis back into change, capacity management with utilization headroom thresholds. SRE practices layered on top: SLI/SLO definition, error budgets, toil reduction, blameless postmortems.

Representative agents (3): `sre-agent`, `change-impact-agent`, `incident-triage-agent`.

### 3. Cybersecurity & Compliance (CyberOps)

Security operations and compliance evidence. Anchored to recognized practices: SSDLC checkpoints (threat modeling, SAST/DAST/SCA in-pipeline, security review at architecture and change gates), vulnerability management lifecycle (CVE intake, CVSS scoring, patch SLA by severity, exception management), compliance evidence collection mapped to control frameworks (NIST 800-53, ISO 27001, SOC 2, `[ENTERPRISE: applicable industry framework — FedRAMP, CMMC, HIPAA, PCI-DSS, etc.]`).

Representative agents (3): `security-review-agent`, `vuln-triage-agent`, `compliance-evidence-agent`.

### Cross-cutting friction surface

The catalog's value depends on the cross-domain agents being real, not nominal:

- `security-review-agent` evaluates artifacts produced by `coder-agent` (code), `sre-agent` (IaC, infrastructure configuration), and `release-agent` (release artifacts).
- `change-impact-agent` evaluates artifacts produced by `sre-agent` (infrastructure changes) and `release-agent` (application changes) before deployment.
- `compliance-evidence-agent` consumes the federation audit bus that all agents emit to; its findings feed back to all three domains.

These cross-cutting agents enforce the domain decomposition operationally. Without them, agents drift into siloed automation and the three-domain structure becomes nominal.

## Snapshot, not living

This baseline is a v1.1-pinned snapshot. Drift between this artifact and the spec is expected as the spec advances; a v1.2 baseline will be a separate `tech-baselines/02-...` directory rather than an in-place revision. Re-instantiation is the discipline; in-place mutation is not.

## Directory shape

```
01-large-enterprise-mvp/
  README.md                            this file
  tech-baseline.md                     populated Appendix D fulfillment record
  meta-harness/
    mode.md                            system orientation (B.2.1)
    mind.md                            reasoning declaration (B.3.1)
    morals.md                          constraint declaration (B.3.2)
    mission.md                         purposive declaration (B.3.3)
    memory.md                          retention declaration (B.3.4)
    means.md                           purposive repertoire (B.3.5)
  execution-governance/
    execution-policy.md                governance-facing policy (B.8.1)
    execution-runtime.md               operational-facing enforcement (B.8.2)
  orchestration/
    orchestrator.md                    top-level orchestration entry (B.5.1.1)
  agents/
    agents.md                          catalog (B.6.1.1)
    coder-agent.md                     DevOps
    reviewer-agent.md                  DevOps
    planner-agent.md                   DevOps
    release-agent.md                   DevOps
    sre-agent.md                       ITIO
    change-impact-agent.md             ITIO
    incident-triage-agent.md           ITIO
    security-review-agent.md           CyberOps
    vuln-triage-agent.md               CyberOps
    compliance-evidence-agent.md       CyberOps
  mechanisms/
    tools.md                           operationally available capacity (B.7.1)
```

## Reading order

1. `README.md` — this file
2. `tech-baseline.md` — the populated Appendix D fulfillment record
3. `meta-harness/mission.md` — what the system is for
4. `meta-harness/morals.md` — what the system must not do
5. `meta-harness/means.md` — purposive repertoire
6. `agents/agents.md` — agent catalog with domain anchors and process references
7. Individual agent contracts as relevant to the reader's role
8. `execution-governance/execution-policy.md` and `execution-runtime.md` — for governance and platform readers

## License

[Creative Commons Attribution 4.0 International (CC BY 4.0)](../../LICENSE) — share and adapt with attribution. Same license as the parent specification.
