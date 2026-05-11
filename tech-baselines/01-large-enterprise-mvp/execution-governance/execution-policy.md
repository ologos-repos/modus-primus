# execution-policy.md — Governance-Facing Policy

**Modus Primus v1.1 reference:** B.8.1
**Owner:** Governance & Strategy, joint with CISO Organization
**Layer:** Execution governance, policy declaration. Read by agents and orchestration before action. Declarative, not enforcement mechanism (which lives in `execution-runtime.md`).

This file declares *what must be enforced* for actions in this enclave. The runtime engine reads `execution-runtime.md` (B.8.2) to know *how to enforce*. The two-artifact split applies the means/mechanisms principle within the execution governance layer per Modus Primus B.8 architectural note.

## B.8.1.1 Validation rules

Every action proposed by an agent must pass validation against:

- **Capability registry conformance:** the agent must be registered for the capability being invoked.
- **Contract conformance:** the action must be enumerated in the agent's contract §2 means authorization or §3 delegation.
- **Scope conformance:** the action target must fall within the agent's declared mission scope, data scope, and operational scope.
- **Trust-level conformance:** the action must be permitted at the agent's current trust level (B.8.1.X below).

All validations are conjunctive. Failure on any validation rejects the action with an audit record.

## B.8.1.2 Human approval gates

Actions requiring human approval within the same session (categorical, not configurable per agent):

- Production deployment trigger
- Vulnerability closure
- Vulnerability exception approval
- Change advisory board approval for non-standard changes
- Emergency-change authorization
- Compliance attestation
- Release approval beyond canary stage
- Incident severity assignment beyond agent recommendation (when agent and assignee disagree by more than one severity level)

Agents may *participate* in these processes (produce inputs, draft proposals, surface findings); the approval act itself is human-authoritative.

## B.8.1.3 Safety verification requirements

Pre-action verification for all production-relevant actions:

- **Reversibility check:** is the action reversible without data loss? If not, the action is reclassified into emergency-change handling.
- **Blast radius check:** does the action affect more than `[ENTERPRISE: blast-radius threshold]` services or assets? If yes, mandatory `change-impact-agent` invocation in the path.
- **Authorization chain check:** does the invoking context have the authority chain required for the action? Authorization is conjunctive across capability registry, contract, runtime authorization, and invoking-context delegation.

Pre-action verification failure rejects the action with an audit record naming the failing check.

## B.8.1.4 Policy enforcement specification

Policy enforcement applies at three layers per PAHA §3:

- **Data-scope enforcement:** operational plane adapters enforce read scope. Agents cannot read outside their declared data scope; attempts produce a categorical violation.
- **Action-scope enforcement:** operational plane adapters enforce write / invoke scope. Agents cannot perform actions outside their declared action scope.
- **Trust-and-autonomy enforcement:** governance plane enforces trust level. Trust escalation requests are governance acts; agents cannot self-escalate.

Enforcement is at the adapter layer (operational plane) for scope concerns; at the governance plane for trust concerns. This split is per PAHA §3 and is what makes the enforcement architecturally trustworthy.

## B.8.1.5 Risk assessment criteria

Each action is classified by risk class at validation time:

- **Class A — advisory only.** Comment emission, finding emission, draft emission. No production state changes. Default for most actions in this baseline.
- **Class B — recommend-with-approval.** Status check emission with downstream gating effect (a failing check may block merge per repository policy). Draft submission to ticketing systems that creates pending work for humans.
- **Class C — automated-with-audit.** Sandbox execution (test runs, IaC dry-runs, scanner execution). Bounded, observable, idempotent, no production state change.
- **Class D — production-impacting.** Not authorized for any agent in this baseline. Production-impacting actions remain human-mediated.

Each agent's contract enumerates its action classes; class D appears in no contract.

## B.8.1.6 Real-world action authorization

Actions that touch production state are categorically Class D and not authorized at this baseline. Production deployment, secret modification, identity store modification, firewall change, database schema change — all human-mediated. The agent's role for these actions is proposal, draft, or assessment; the action itself is taken by a human or by a human-triggered automation system (CI/CD platform, IaC platform, change management system) with the agent's output as input.

This is intentionally conservative for an MVP baseline. Trust escalation to permit selected Class D actions for specific agents requires a governance act per §9.4 (federation schema review) and per the trust escalation model in PAHA §3.

## B.8.1.7 Escalation triggers

Runtime triggers for escalation enforcement (the *criteria* that fire escalation; the runtime *mechanism* lives in B.8.2):

- **Authorization gap:** action requested outside contract authorization → escalation to capability registry owner.
- **Scope-boundary violation in invocation:** invocation requests scope outside declared mission → escalation to mission owner.
- **Policy ambiguity:** action requires policy interpretation not derivable from policy library → escalation to policy owner.
- **Capability-gap:** required capability not in means inventory → escalation to means owner; may trigger means election review (§9.7).
- **Sustained refusal pattern:** an agent refuses a class of requests repeatedly → drift detection trigger (B.10.2.1).
- **Direct-escalation criteria match:** per each agent contract's §4 direct escalation triggers.

## B.8.1.8 Approval workflow specifications

Approval workflows are external to this baseline (they live in `[ENTERPRISE: change management system]`, `[ENTERPRISE: GRC platform]`, repository policy configurations, ticketing platforms). This file declares the *requirement* that approval workflows exist and that agents emit proposals into them; the workflows themselves are enterprise concerns.

The federation schema requires that approval decisions be recorded as audit events on the federation bus so that compliance evidence collection (`compliance-evidence-agent`) can verify approval coverage retrospectively.

## B.8.1.9 Audit logging requirements

Every action by every agent in this enclave emits at least the following audit signal to the federation bus:

- Agent identity (service identity)
- Invocation context (invoker identity, source system, source event id)
- Action class (A / B / C / D — though D should never appear in this baseline)
- Action subject (target artifact id, target service, target asset)
- Decision basis (citation pattern matching the agent's contract §6 explainability surfacing)
- Pre-action validation outcomes
- Post-action outcome (success / refusal / error)
- Timestamp
- Trace correlation id

What is stored is per `memory.md` audit retention class (B.3.4.9); where it is stored is `[ENTERPRISE: audit aggregation / SIEM]`; how long is per regulatory minimum and internal policy.

## B.8.1.10 Required compliance artifacts

The enclave produces the following compliance artifacts on a recurring cadence:

- **Continuous:** audit bus signal (per action)
- **Per audit window:** evidence package per active control framework (produced by `compliance-evidence-agent`)
- **Per quarter:** tech-baseline review evidence (per Modus Primus §9.2)
- **Per annual cycle:** WBS conformance verification (per Modus Primus §7.2)
- **Per substrate change:** substrate substitution V&V evidence (per §7.5)
- **Per mission change:** mission alignment validation (per §7.3)

Artifact integrity is enforced through the audit federation schema; missing artifacts at audit windows surface as gaps through `compliance-evidence-agent`.

## Trust escalation model

Trust escalation states inherited from PAHA §3:

- **Advisory only** — agent emits findings / proposals; humans decide and act. Default at this baseline for most actions.
- **Recommend-and-approve** — agent emits a recommendation that a human must explicitly approve before action. Status-check-with-gating-effect falls here.
- **Automated-with-audit** — agent acts within bounded scope with full audit; humans review on cadence rather than per-action. Sandboxed execution falls here.
- **Fully autonomous** — agent acts without per-action human review. Not authorized at this baseline.

Trust escalation transitions are governance acts per §9.4. Audit evidence over `[ENTERPRISE: trust escalation evidence window]` is the criterion; the criterion is satisfied through demonstrated behavioral baseline + clean drift detection record + clean policy deviation record over the window.

---

This file is read by agents at invocation and by the runtime engine before each action. Revisions are governance acts requiring Governance & Strategy + CISO joint approval per Modus Primus §9.1 / §9.4.
