# execution-runtime.md — Operational-Facing Enforcement Mechanics

**Modus Primus v1.1 reference:** B.8.2
**Owner:** Platform Engineering
**Layer:** Execution governance, runtime enforcement. Reads `execution-policy.md` (B.8.1) for what to enforce; specifies how. Mechanism, not policy.

## B.8.2.1 Pre-action validation gates

Every agent action passes through pre-action validation before invocation. The validation pipeline:

1. **Capability registry check.** Query registry for `(agent_identity, capability, scope)` triple. Reject on miss.
2. **Contract authorization check.** Parse agent contract; verify action falls within §2 means or §3 delegation. Reject on miss.
3. **Scope conformance check.** Verify action target matches mission scope, data scope, operational scope per contract. Reject on miss.
4. **Trust level check.** Verify the action's risk class (per `execution-policy.md` B.8.1.5) is permitted at agent's current trust level. Reject on miss.
5. **Resource limit check.** Verify proposed resource consumption (compute, memory, tokens, cost, time) within configured per-invocation limits. Reject on miss with budget-exceeded code.
6. **Policy-clause check.** For actions with declared policy dependencies (security review, compliance evidence), verify the action's invocation matches policy library terms at current version.

All checks are conjunctive; first failure short-circuits and rejects.

Rejection emits a structured audit record with the failed-check code and the input that caused failure.

## B.8.2.2 Approval-workflow runtime

For actions requiring human approval gates (`execution-policy.md` B.8.1.2), the runtime:

- Refuses to perform the action under agent identity alone.
- Emits a proposal record to the appropriate human-facing system (`[ENTERPRISE: change management system]`, `[ENTERPRISE: ticketing platform]`, repository policy gate, etc.).
- Records the proposal in the federation audit bus with state `awaiting-human-approval`.
- Waits for an approval signal returning through the federation bus (the approval is recorded as a human-acted audit event by the upstream system, then bridged to this bus).
- On approval signal, the action is *not* executed by the runtime; the action's execution remains at the upstream system that received the approval. The runtime records `approval-received` and `outcome-pending`.
- Outcome (success / failure of the upstream-executed action) flows back via observability or upstream-system audit bridging.

This is the operational realization of the human-action-authority principle. The runtime does not "wait and then act"; the upstream system acts and the runtime records.

## B.8.2.3 Transaction controls

Agent actions that produce multiple federated effects (audit record, finding attachment, downstream invocation, etc.) are transactional at the level the federation supports:

- All effects of a single action either succeed together or none persist.
- Implementation: a saga-pattern coordinator emits compensating actions for any partial failure. The compensator's actions are themselves recorded in the audit bus.
- Cross-system transactional integrity (e.g., comment posted but change-record attachment failed) is not assumed by the underlying systems; the saga coordinator handles the inconsistency.

Idempotency is required for all Quartus invocations to enable saga retries; each agent contract verifies idempotency in §3.

## B.8.2.4 Rollback procedures

Categorical:

- Sandboxed execution (Class C in `execution-policy.md` B.8.1.5): no rollback needed; sandbox dissolves at session end.
- Proposal / draft emission (Class A): rollback is recall (proposer system records a recall event; the propose-recall pair persists in audit).
- Status-check or attachment emission (Class B): rollback is emit-corrective-record (the corrective record updates the upstream-system state; both records persist in audit).
- Production-impacting (Class D): not authorized at this baseline; rollback is N/A.

Rollback is always a forward-emitted corrective action, never a state mutation that erases evidence.

## B.8.2.5 Environment isolation

Per-agent runtime environments are isolated:

- Distinct service identity per agent (rotated per `[ENTERPRISE: service identity rotation policy]`).
- Distinct network egress allowlist per agent, configured at the operational plane and verified at runtime invocation.
- Distinct credential scope per agent (no shared secrets across agents).
- Distinct storage namespace for per-agent persistent state per `memory.md` B.3.4.2.

Cross-agent isolation breach is a categorical violation. Detection at the operational plane (credential or network policy violation) immediately suspends the offending agent and emits a critical audit event.

## B.8.2.6 Sandbox enforcement

Sandboxed execution (Class C per `execution-policy.md` B.8.1.5):

- Runs in `[ENTERPRISE: sandboxed compute environment — typically a container runtime or microVM with no production network access]`.
- Network egress restricted to declared endpoints per agent contract; default-deny.
- Filesystem access scoped to per-session ephemeral storage; no persistent or shared filesystem access.
- Resource limits enforced by the sandbox runtime (CPU, memory, time, disk).
- Termination at session end; no persistent state in sandbox.

## B.8.2.7 Resource limit enforcement

Resource limits configured per agent per invocation:

- **Compute time limit:** per-invocation wall-clock budget per agent contract.
- **Token / inference budget:** per-invocation cost budget per agent contract, denominated in `[ENTERPRISE: inference cost accounting unit]`.
- **Memory limit:** per-invocation memory ceiling per agent contract.
- **Egress rate limit:** per-invocation network calls per agent per unit time.

Limits enforced by the runtime substrate; exceedance terminates the invocation and emits an audit record. Exceedance does not produce partial output that escapes audit; partial output at termination flows through the audit bus as an "invocation-truncated" record.

## B.8.2.8 Real-world action gating

Class D production-impacting actions are not invocable by any agent at this baseline. The gating mechanism:

- Credentials required for production actions are not held by any agent's service identity.
- Network paths required for production actions are not open from any agent's runtime environment.
- Even if a hypothetical agent constructed a Class D action request, no execution path exists.

Defense in depth: the credential-absence guarantee is the primary gate; network and runtime restrictions are redundant gates.

## B.8.2.9 Failure containment

Agent failures are contained:

- An agent failure does not propagate to other agents (process / namespace isolation).
- An agent failure does not propagate to orchestration (orchestration treats per-agent invocation outcomes idempotently).
- Repeated failures within `[ENTERPRISE: failure threshold window]` trigger automatic agent suspension and human notification.
- Suspended agents are not invocable until cleared by `[ENTERPRISE: agent operations on-call rotation]`.

Failure containment is the operational realization of trust-but-verify: agents are trusted with their declared scope until evidence of failure, at which point the runtime contains the agent rather than ignoring the signal.

## B.8.2.10 Runtime audit emission

Every action emits the audit signal specified in `execution-policy.md` B.8.1.9 to the federation audit bus. Emission is:

- **Synchronous to action.** Audit emission precedes (or co-emits with) the action's effect; an action whose audit emission fails is itself a failure.
- **Schema-conformant.** All records conform to the federation audit schema; non-conformant records are rejected at the bus and produce an audit-schema-violation event.
- **Tamper-evident.** Records are signed with the runtime engine's identity and chained per the federation schema's tamper-evidence protocol.
- **Replicable.** Records are replicated across `[ENTERPRISE: audit aggregation replication tier]` for durability and cross-enclave aggregation.

The runtime engine itself is observable: audit-emission failure is observable through observability platform alarms, and audit-emission latency is an SRE-managed signal.

---

## Runtime engine architecture summary

The runtime engine is a per-invocation validation + emission pipeline that sits between the agent's substrate and the operational plane adapters. Architecturally:

```
Agent invocation (proposed action)
       ↓
Pre-action validation pipeline (B.8.2.1)
   ↓ pass                        ↓ fail
Resource budget check               Audit emission (rejection)
   ↓ pass                        ↓ rejection record
Transactional wrap (B.8.2.3)
   ↓
Operational plane adapter call
   ↓
Audit emission (action outcome)
   ↓
Post-action verification
```

The pipeline is per-invocation; agents do not bypass it. Per-agent invocation latency overhead is `[ENTERPRISE: runtime overhead budget]` and is the cost of governance enforcement at this layer.

---

This file specifies enforcement mechanics. Revisions are governance acts requiring Platform Engineering + Governance & Strategy joint approval per Modus Primus §9.1 / §9.4 (the latter if federation schema is affected).
