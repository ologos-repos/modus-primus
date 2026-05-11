# memory.md — What the System Remembers and Forgets

**Modus Primus v1.1 reference:** B.3.4
**Owner:** Data Governance
**Layer:** Meta-harness retention declaration. Declarative; retention *infrastructure* lives in the Observability layer (B.9 / B.10).

## B.3.4.1 Context retention

Three retention classes:

- **Session-scoped:** memory retained for the duration of a single invocation tree (Quartus + Quintus invocations under one Tertius invocation). Discarded at session end. All sensitive data classifications above L1 fall into this class by default.
- **Persistent within Tertius lifecycle:** memory retained for the agent's operational lifetime. Bounded to repository-anchored facts (file structure, type signatures, capability registry state), service-topology facts (consumed from CMDB), or compliance-mapping facts (control library state). No persistent retention of human-supplied operational context.
- **Audit-retention:** retained per regulatory and compliance obligation. Bounded to audit signals emitted to the federation bus and to evidence packages submitted by `compliance-evidence-agent`. Retention duration is set by the controlling regulatory regime per `[ENTERPRISE: audit retention policy]`.

## B.3.4.2 Persistence policies

- Session-scoped data persists only in the agent's runtime memory; it is not written to any durable store.
- Tertius-persistent data persists in `[ENTERPRISE: agent state store]` with access controls inheriting the agent's service identity.
- Audit-retention data persists in `[ENTERPRISE: audit aggregation / SIEM]` and in `[ENTERPRISE: GRC platform]` per the federation schema for audit records.

Cross-class promotion (session → persistent → audit) requires explicit policy declaration. No automatic promotion is permitted.

## B.3.4.3 Retrieval rules

Agents retrieve from:

- Session-scoped memory: free; within the invocation tree.
- Tertius-persistent memory: per-agent only. No cross-agent retrieval of persistent memory; agents do not read each other's persistent state directly. Cross-agent context flows through the federation audit bus, not through memory access.
- Audit-retention memory: read-only and access-controlled. `compliance-evidence-agent` is the primary authorized consumer for compliance evidence retrieval; other agents access audit retention only for declared historical-correlation use cases enumerated in their contracts.

## B.3.4.4 Session continuity

Sessions are bounded by Tertius invocation lifetime. There is no cross-session continuity at the Tertius level beyond what is captured in audit retention. This is a deliberate constraint: agents do not accumulate session-to-session operational memory of human-supplied context because that accumulation produces governance and compliance risk that outweighs the operational benefit at this maturity tier.

Sessions can be reconstructed from audit retention if needed for post-incident review or audit response; this is a human-mediated retrieval, not an agent-mediated one.

## B.3.4.5 Knowledge grounding

Agent reasoning is grounded in:

- The agent's contract (declarative ground truth for what the agent is and what it may do)
- The meta-harness files (declarative ground truth for system disposition)
- The capability registry (declarative ground truth for what agents and substrates are available)
- The invoking system (primary evidence for the task at hand)

Substrate-native knowledge (training-set knowledge of the underlying open-weights model) is treated as supplementary, not authoritative. Substrate-asserted facts that conflict with grounded sources lose; substrate-asserted facts on topics outside grounded source coverage are flagged as substrate-asserted.

## B.3.4.6 State management

Agent runtime state is managed by `execution-runtime.md` (B.8.2). Per-agent state stores enforce:

- Encryption at rest per `[ENTERPRISE: encryption policy]`
- Access controls scoped to the agent's service identity
- Audit logging of state access (both reads and writes) into the federation bus
- Retention enforcement against this file's classifications

## B.3.4.7 Memory boundaries

The boundaries between memory classes are enforced at the operational plane (storage tier ACLs, audit log access controls) and validated at the runtime plane (pre-action validation rejects cross-class promotion attempts). Memory boundary violations are categorical findings; they do not silently log as benign access.

## B.3.4.8 Temporal relevance

- Session-scoped memory is current by definition.
- Tertius-persistent memory may go stale; staleness detection is per-agent (each agent's contract declares its persistent-memory refresh discipline).
- Audit-retention memory is point-in-time correct; later corrections do not modify past audit records, they emit corrective records.

The runtime layer monitors temporal staleness as a signal class; sustained staleness in an agent's persistent memory triggers refresh and, if recurrent, contract revision.

## B.3.4.9 Audit history retention

Refers to `execution-governance/execution-runtime.md` (B.8.2.10 audit emission) for what is audited and to `[ENTERPRISE: audit aggregation / SIEM]` for where it is stored. Audit retention duration is set by:

- **Regulatory minimum** per active control framework (`[ENTERPRISE: applicable industry framework — FedRAMP, SOC 2, ISO 27001, HIPAA, PCI-DSS]`)
- **Internal policy minimum** per `[ENTERPRISE: internal audit retention policy]`
- **Operational maximum** per `[ENTERPRISE: storage capacity policy]`

Effective retention is `max(regulatory, internal) ≤ retention ≤ operational maximum`. Retention shorter than regulatory minimum is a categorical violation enforced at storage configuration.

## B.3.4.10 Recall prioritization

When agent context capacity is bounded (substrate context windows; observability query result sets), recall priority is:

- The invocation's primary evidence (top priority)
- The agent's contract and the meta-harness files (always-in-context; not subject to truncation)
- Recent prior findings on the same artifact (high priority)
- Historical patterns at the agent class level (medium priority)
- Cross-agent context from the federation bus (low priority unless declared as primary by the agent's contract)

Truncation policy per agent: declared in each contract's §2 memory scope.

## Sensitive data handling

Operational data classified above L1 is session-bounded by default. Specific agent contracts may declare narrow exceptions for persistent retention of L2+ data (e.g., `vuln-triage-agent` retains vulnerability records at regulatory minimum); each exception is enumerated in the agent's contract and approved at §9.5 review. Default-deny applies; exceptions are explicit.

---

This file is read at orchestration boot and at each agent invocation. Revisions require Data Governance approval and may trigger federation schema review per Modus Primus §9.4 if audit signal definitions are affected.
