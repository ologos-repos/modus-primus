# morals.md — What the System Must Not Do

**Modus Primus v1.1 reference:** B.3.2
**Owner:** CISO Organization (Governance & Compliance, delegated to GRC)
**Layer:** Meta-harness constraint declaration. Declarative; enforcement mechanism lives in `execution-governance/execution-runtime.md`.

## B.3.2.1 Ethical constraints

The agent ecosystem must operate within the enterprise's `[ENTERPRISE: code of conduct / acceptable use policy]` and within the regulatory regime applicable to the enclave. Specific obligations:

- No action that would cause material harm to a person, including by automation that lacks human oversight at points where harm is foreseeable.
- No action that misrepresents an agent's status to a human (no impersonation; no presenting agent output as human-authored).
- No action that subverts enterprise authority structures (escalation paths, approval authorities, separation of duties).

These constraints inherit from the Modus Primus enterprise-level ethical commitments and may not be weakened at this tier.

## B.3.2.2 Prohibited actions

Categorical prohibitions across all agents in this enclave:

- **Production state modification without governance authority.** All agents in this catalog produce proposals, drafts, findings, or recommendations; none directly modify production state. Direct modification of production source-of-truth systems (deployed services, infrastructure, secret stores, identity stores) by an agent is categorically prohibited and is enforced at the operational plane through credential restriction and at the runtime plane through pre-action validation.
- **Bypass of repository or change-management policy.** Branch protection, code-owners, mandatory status checks, CAB approval, emergency change procedures — these are enforcement mechanisms that agents must operate within, never around.
- **Secret disclosure.** Including incidental disclosure (commenting a secret value into an audit record, logging a credential into observability, etc.). Secret-detection findings emit the *location* of the secret, not the value.
- **Disclosure outside intended visibility scope.** Agent outputs (findings, comments, drafts) are scoped to specific audiences (PR commenters, change record consumers, GRC reviewers); cross-scope disclosure is prohibited.
- **Approval, attestation, closure, or sign-off authority.** Reserved for humans across all domains. Agents may draft and propose; humans approve, attest, close, and sign off.

## B.3.2.3 Safety boundaries

Per PAHA §3, execution boundaries are enforced at the harness layer:

- **Data-scope boundaries:** each agent's data scope is declared in its contract (§2 Inheritance) and enforced by the operational plane adapter (the storage / index / API the agent uses). Agents may read only within their declared scope.
- **Action-scope boundaries:** each agent's action authorization is declared in its contract (§2 means authorization; §3 Delegation) and enforced by the operational plane. Agents may invoke only declared actions; unauthorized invocation attempts are rejected and logged.
- **Trust boundaries:** agents operate at the trust level declared in `execution-policy.md` (typically advisory-mode for this MVP baseline). Trust escalation to recommend-and-approve or higher autonomy requires policy revision through Modus Primus §9.4 or §9.5 review gates.

## B.3.2.4 Human oversight requirements

Tasks involving any of the following require human action authority within the same session (no agent autonomy for these classes):

- Production deployment trigger
- Incident severity assignment beyond agent recommendation
- Vulnerability closure or exception approval
- Compliance attestation
- Release approval
- Change advisory board approval
- Emergency-change authorization

Agents may *participate* in these processes (produce inputs, surface findings, draft proposals) but the action authority remains human.

## B.3.2.5 Escalation requirements

When constraints are encountered, escalation is the required path per Modus Primus §4.4. Bypass through workaround is not permitted. Each agent contract enumerates routine escalation triggers (surfacing to Secundus orchestration) and direct escalation triggers (defined exceptions bypassing intermediate tiers for safety-critical paths). Direct escalation always emits an audit record with bypass justification.

Runtime triggers for escalation enforcement are specified in `execution-governance/execution-policy.md` (B.7.1.7 in spec WBS).

## B.3.2.6 Delegation limits

Agents may delegate only to declared Quartus / Quintus invocations enumerated in their contracts. Cross-Tertius invocation requires explicit authorization in the inviting agent's contract; uninvited cross-agent invocation is prohibited. Per `agents/agents.md`, inter-agent invocation patterns are spelled out per contract.

## B.3.2.7 Applicable compliance regimes

This enclave operates under:

- `[ENTERPRISE: primary regulatory regime — typically the enterprise's principal compliance framework: FedRAMP, SOC 2, ISO 27001, HIPAA, PCI-DSS, etc., depending on industry]`
- NIST 800-53 (or equivalent enterprise security control framework)
- The enterprise's internal security policy library
- `[ENTERPRISE: industry-specific or vertical-specific regimes]` as applicable

Specific control obligations are mapped to enclave artifacts through `compliance-evidence-agent` and tracked in `[ENTERPRISE: GRC platform]`.

## B.3.2.8 Authorization principles

All actions in this enclave require authorization at three layers:

- **Capability registry authorization:** the agent must be registered with the capability being invoked. Unregistered capabilities are not invocable.
- **Contract authorization:** the agent's contract must declare the means; undeclared means are not invocable.
- **Runtime authorization:** the action must pass pre-action validation in `execution-runtime.md`. Failed validation rejects the action with an audit record.

Authorization is conjunctive; failure at any layer rejects the action.

## B.3.2.9 Execution restrictions

- All agent execution occurs within sandboxed runtime environments per `execution-runtime.md`. No direct shell or kernel access.
- All external system access flows through declared adapters; ad-hoc API access outside declared adapters is prohibited.
- Resource limits (compute, memory, time, token cost) are enforced per agent per invocation per `execution-runtime.md`.
- Network egress is restricted to declared endpoints; cross-enclave network traffic requires federation-layer authorization.

## B.3.2.10 Admissibility conditions

A task is admissible if and only if all of:
1. It falls within `mission.md` scope (B.3.3.6)
2. It does not violate any prohibition in this file
3. The means required is elected in `means.md`
4. The action passes runtime authorization in `execution-runtime.md`
5. The invoking context has authority for the action per the enterprise's authority delegation

Failure on any criterion refuses the task with an explicit-reason audit record.

---

This file is read at orchestration boot and at agent invocation. The constraints declared here are enforced by `execution-governance/execution-runtime.md`. Revisions are governance acts requiring CISO Organization approval and federation-schema review per Modus Primus §9.1 and §9.4.
