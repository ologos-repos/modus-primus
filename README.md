# Modus Primus

**A Capability-Centric Framework for Governed AI Ecosystems in Sovereignty-Bounded Enterprises**

This repository is the public home of two complementary documents:

| Document | Role | File |
|---|---|---|
| **Portable Agent Harness Architecture (PAHA)** | The architectural framework. Defines a meta-harness pattern providing centralized governance, bounded execution, and substrate arbitration over which fit-for-purpose operational consoles and composable agents are instantiated. Three architectural planes (governance, cognitive, operational); seven minimum-viable services; five primitives. Rev 2.2, February 2026. | [`PAHA-v2.2.pdf`](PAHA-v2.2.pdf) |
| **Modus Primus Engineering Specification** | The engineering companion subordinate to PAHA. Specifies the concrete services, contracts, and interaction shapes implementing the PAHA pattern as a minimum viable harness. v1.1. | [`modus-primus-spec-v1.1.pdf`](modus-primus-spec-v1.1.pdf) |
| Executive overview deck | Condensed executive-audience summary of the framework. | [`modus-primus-executive-v1.pptx`](modus-primus-executive-v1.pptx) |

## At a glance

The current generation of enterprise AI deployments is organized around *assistants* — vendor copilots, orchestration runtimes, foundation-model interaction surfaces — with governance, identity, and execution control bolted on around them. PAHA argues this assistant-centric pattern is structurally inadequate for enterprises operating under sovereignty constraints, multi-vendor obligations, or cross-enclave security boundaries.

The proposed alternative is a **meta-harness as the durable architectural layer**:

- **Governance plane** (slowest-changing, evolves over years) — identity, authorization, policy, approvals, audit, provenance. Substrate-agnostic. Survives substrate changes, agent retirements, and console refactoring.
- **Cognitive plane** (months) — agent orchestration, reasoning, planning, retrieval, memory, context management, evaluation. Substrate adapters at the boundary make cognitive substrates interchangeable.
- **Operational plane** (fastest) — tooling, infrastructure, enterprise systems, repositories, runtime actions. Heterogeneous by nature; the harness accommodates rather than uniformizes.

The framework's value proposition rests on the **rate-of-change separation**: enterprise governance evolves on cycles measured in years; cognitive substrates evolve on cycles measured in months. Coupling them tightly imposes governance debt the enterprise cannot pay.

## Scope qualifier

The pattern is grounded in defense IT realities (classified network segmentation, ITAR/EAR, FedRAMP, CMMC, ATO cycles, air-gapped deployment) because those constraints make the value visible. The architectural pattern generalizes beyond defense; the qualified market thesis is that *orchestration supremacy* applies most strongly to organizations whose security posture or regulatory regime prevents acceptance of vendor-integrated orchestration. For organizations with single-vendor consolidation strategies in commercial environments, vendor-integrated orchestration may be the more economically rational choice — and the pattern proposed here represents unnecessary overhead.

## Author

**James (JD) Longmire**
Northrop Grumman Fellow (unaffiliated research)
Chief Architect — Digital Ecosystems
ORCID: [0009-0009-1383-7698](https://orcid.org/0009-0009-1383-7698)
Correspondence: jdlongmire@outlook.com

## Status

Active. PAHA Rev 2.2 (February 2026) is the current architectural reference. Modus Primus v1.1 is the engineering companion. Subsequent revisions will be released through this repository.

## License

[Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE) — share and adapt with attribution.
