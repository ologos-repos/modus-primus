# orchestrator.md — Secundus Orchestration

**Modus Primus v1.1 reference:** B.5.1.1
**Owner:** Orchestration Owner (Platform Engineering)
**Layer:** Orchestration top-level entry. Routes work to Tertius agents per the capability registry. Sequencing mechanics; not policy.

## Top-level entry

The Secundus orchestrator is the canonical entry point for all work flowing into this enclave from external triggering systems (PR webhooks, change-record creation, incident detection, CVE feed, audit-window scheduler, on-demand human invocation). It is not the only invocation surface — agents may be invoked directly by other agents per declared invitation patterns in `agents/agents.md` — but it is the primary surface and the one whose configuration determines the enclave's default behavior.

## Routing

Routing decisions are capability-registry-driven. For each incoming event, the orchestrator:

1. Identifies the event class (PR-event, change-event, incident-event, CVE-event, audit-window-event, on-demand-event).
2. Queries the capability registry for agents registered against the event class.
3. Filters by mission scope (per `meta-harness/mission.md`): excludes agents whose mission scope does not cover the event's subject.
4. Filters by current trust level: excludes agents currently suspended or under runtime-assurance review with restricted authorization.
5. Selects the appropriate agent (typically a single primary agent per event class; multi-agent dispatch is the exception, not the default).
6. Issues a Tertius invocation with the event context, the invoking authority chain, and the federation audit correlation id.

Routing is deterministic per registry state; two identical events route identically. Routing decisions are auditable.

## Delegation (per Modus Primus §4.3)

Delegation flows strictly tier-by-tier:

- Primus → Secundus: federation contract inheritance; no operational delegation (Primus does not execute work).
- Secundus → Tertius: this orchestrator's primary function. Routes to agents per the capability registry; passes mission, morals, memory, means context per inheritance contract.
- Tertius → Quartus: per-agent contracts authorize specific Quartus tool invocations (B.7 mechanism layer adapters).
- Tertius → Quintus: per-agent contracts authorize parallel patterns where declared.

The orchestrator does not invoke Quartus or Quintus directly. Cross-tier short-circuits are categorical violations.

## Sequencing

Per-task sequencing is bounded by the Tertius agent's contract (each contract declares its sequencing patterns under §3 Delegation). The orchestrator does not impose Secundus-level sequencing on a Tertius agent's internal logic; it sequences only at the inter-agent level.

Inter-agent sequencing patterns documented for this enclave:

- **DevOps PR sequence:** `reviewer-agent` (always) → `security-review-agent` (conditional on SSDLC trigger) → final human review.
- **Release sequence:** `release-agent` → `change-impact-agent` (mandatory) → `security-review-agent` (conditional) → CAB / human approval.
- **Incident sequence:** `incident-triage-agent` → optionally `change-impact-agent` (inverse query: did a recent change correlate?) → human on-call response.
- **CVE sequence:** CVE feed event → `vuln-triage-agent` → optionally `security-review-agent` (if active artifact under review is affected) → `compliance-evidence-agent` indirect via audit bus.
- **Compliance audit-window sequence:** scheduled trigger → `compliance-evidence-agent` (primary) → human GRC review.

Sequencing patterns are documentation, not configuration. The runtime sequencing is driven by per-agent invitation patterns declared in each contract; this catalog represents the expected typical sequences.

## Coordination

Multi-agent coordination patterns documented in this enclave:

- **DevOps × CyberOps coordination at SSDLC security gate:** `reviewer-agent` invokes `security-review-agent` on trigger pattern match; `security-review-agent` invokes `vuln-triage-agent` on CVE-class scanner finding. Coordination occurs through invitation patterns, not through the orchestrator.
- **ITIO × DevOps coordination at release readiness:** `release-agent` invokes `change-impact-agent` mandatorily; `change-impact-agent` consumes context from `sre-agent` outputs indirectly via the audit bus.
- **Cross-domain coordination via audit bus:** `compliance-evidence-agent` consumes all other agents' audit signals. Coordination via the bus is read-only and asynchronous.

The coordination catalog above is a documentation artifact reflecting the per-agent contract design. The orchestrator does not implement coordination logic; it implements the entry point. Coordination is per-agent.

## Arbitration

When two or more agents are registered for the same event class and routing produces a tie, the orchestrator arbitrates by:

1. **Mission specificity:** the agent whose mission scope is more specific to the event subject wins.
2. **Trust level:** the agent at higher trust level wins (only if the action is permitted at that trust level for this event class).
3. **Recent behavioral baseline:** the agent with cleaner recent runtime-assurance evidence wins.
4. **Round-robin** as final tie-breaker, recorded in audit.

Arbitration decisions are auditable; sustained arbitration in favor of one agent over another is a signal for capability-registry review.

## Load balancing

Within an agent, the orchestrator distributes work across instance pool per `[ENTERPRISE: orchestration platform load balancing]`. Across agents, load balancing does not apply — work is routed by capability registry, not by load.

## Task decomposition

Task decomposition is a Tertius-agent role (`planner-agent`); the orchestrator does not decompose tasks itself. The orchestrator does, however, recognize decomposition output (a planner-agent-emitted task graph) and routes the resulting sub-tasks per their declared agent assignments. Human-assigned routing of sub-tasks overrides agent-emitted assignments.

## Execution planning

Per-invocation execution planning (which tools, in what order, with what parameters) is internal to each Tertius agent. The orchestrator's planning is restricted to the inter-agent layer (which agents, in what sequence).

## Recovery handling

When a Tertius invocation fails:

- **Retriable failures** (timeout, transient downstream error, resource limit, sandbox setup error): retried per per-agent retry policy (idempotent invocations only). After exhaustion, surfaces to invoking system as failure-event.
- **Non-retriable failures** (validation rejection, contract violation, scope violation, secret-detection, escalation trigger): not retried. Surfaces to invoking system and emits a finding to audit.
- **Agent suspension during retry:** if the agent is suspended mid-invocation, the in-flight invocation is allowed to complete or hits its time limit; subsequent invocations are routed to a degraded path or refused with explicit suspension reason.
- **Compensating actions:** per `execution-runtime.md` B.8.2.3 transaction controls; the orchestrator emits compensators for failed actions that left partial effects.

Failure handling is observable end-to-end via audit signals.

---

## Federation pattern interaction

The Secundus orchestrator inherits from the Primus federation specification:

- Inheritance contract on invocation: every Tertius invocation carries the inheritance context from Primus → Secundus → Tertius (mission, morals, memory, means subset, federation schema obligations).
- Escalation paths: routine escalations flow to this orchestrator and then to the appropriate enterprise-level resolution; direct escalations bypass per `meta-harness/morals.md` B.3.2.5.
- Federation audit: every orchestrator action emits a federation-bus event with cross-tier correlation ids so post-hoc analysis can reconstruct the full invocation chain.

The orchestrator does not federate cross-enclave (peer-Modus-Secundus); cross-enclave coordination is a Primus-level federation concern, not a Secundus orchestrator concern.

---

This file is read at orchestrator boot. Revisions to routing or sequencing logic are governance acts requiring Orchestration Owner approval and may trigger federation-schema review per Modus Primus §9.4 if the federation audit contract is affected.
