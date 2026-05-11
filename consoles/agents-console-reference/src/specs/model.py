"""AgentSpec — the immutable identity of an agent at run time.

Each spec is a markdown file at means/agents/specs/<domain>/<name>.md with
YAML frontmatter declaring runtime parameters and a body that becomes the
system prompt. The loader produces an AgentSpec; runs reference the
spec_hash so behavior changes from prompt edits are visible in the audit.

Phase 1 fields:
- name, domain, fork  — identity / categorization
- model               — provider:model string parsed by the backend
- system_prompt       — body of the markdown
- timeout_s           — wall-clock cap

Phase 2 adds:
- tools  — Optional[list[str]] (None → fork defaults; [] → no tools)
- cwd    — Optional[str] (None → per-run workspace under data/workspaces/)

Phase 3+ adds:
- qa     — QA criteria
- requires_approval — Phase 4 approval-gate matchers
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class AgentSpec:
    name: str
    domain: str
    fork: str               # 'dev' | 'infraops'
    model: str
    system_prompt: str
    timeout_s: int
    # Phase 2 semantics:
    #   None  → use fork defaults (resolved by runtime/fork_defaults.resolve_tools)
    #   []    → explicit no tools (single-shot, like Phase 1)
    #   [...] → exactly that allowlist
    # Backend code MUST NOT read this directly — go through resolve_tools().
    tools: Optional[list[str]]
    qa: dict[str, Any]      # Phase 3 (QA pass)
    cwd: Optional[str]      # Phase 2: subprocess cwd override; None → per-run workspace
    # Phase 4: gate the run on human approval. When True, spawn creates an
    # `awaiting_approval` row instead of launching the daemon; an approver
    # decides via /runs/{id}/approve or /deny.
    requires_approval: bool
    spec_path: Path
    spec_hash: str          # sha256 of file bytes

    # Phase 6: provider/model_id are derived from `model:` so specs can declare
    # `model: openai:gpt-4o-mini`, `model: ollama:peakai/qwen3:14b`, etc. Bare
    # values (e.g. `model: sonnet`) default to provider `claude` so existing
    # specs keep working unchanged.
    @property
    def provider(self) -> str:
        prefix, sep, _ = self.model.partition(":")
        return prefix.lower() if sep else "claude"

    @property
    def model_id(self) -> str:
        prefix, sep, rest = self.model.partition(":")
        return rest if sep else prefix

    def to_summary(self) -> dict:
        """Lightweight dict suitable for the GET /agents listing.

        `tools` is projected as the *effective* allowlist (post fork-default
        resolution) so the UI sees what will actually be passed to claude.
        """
        # Local import: runtime imports specs.model elsewhere; avoid the cycle.
        from ..runtime.fork_defaults import resolve_tools

        return {
            "name": self.name,
            "domain": self.domain,
            "fork": self.fork,
            "model": self.model,
            "provider": self.provider,
            "timeout_s": self.timeout_s,
            "tools": resolve_tools(self),
            "qa": self.qa,
            "cwd": self.cwd,
            "requires_approval": self.requires_approval,
            "spec_hash": self.spec_hash,
        }


@dataclass
class WorkflowStep:
    """One step in a linear workflow chain. Phase 8 keeps these minimal:
    each step references an existing agent by name and supplies a prompt
    template that may use `{input}` (the workflow's initial input) and
    `{prev_output}` (the previous step's concatenated text output)."""
    id: str          # for human-readable step identification in logs/UI
    agent: str       # name of the agent spec to invoke (must exist at run time)
    prompt: str      # template string passed through render_prompt


@dataclass
class WorkflowSpec:
    """A linear chain of agent invocations. Phase 8 is sequential-only —
    DAG topology is deferred. The runtime spawns each step's agent run as
    a normal child run linked back via `parent_workflow_run_id`, so QA,
    approvals, and audit all compose for free."""
    name: str
    domain: str
    description: str             # markdown body, shown in the modal
    steps: list[WorkflowStep]
    spec_path: Path
    spec_hash: str

    def to_summary(self) -> dict:
        """Listing dict — excludes step bodies to keep /workflows lightweight."""
        return {
            "kind": "workflow",
            "name": self.name,
            "domain": self.domain,
            "description": self.description,
            "step_count": len(self.steps),
            "spec_hash": self.spec_hash,
        }

    def to_detail(self) -> dict:
        """Detail dict — includes the full step list for the modal."""
        body = self.to_summary()
        body["steps"] = [
            {"id": s.id, "agent": s.agent, "prompt": s.prompt}
            for s in self.steps
        ]
        return body


@dataclass
class TriggerSpec:
    """Phase 9: scheduled trigger that fires an existing agent or workflow.

    The schedule is a 5-field cron expression interpreted in system-local
    time. Targets are referenced by name (must exist when the scheduler
    fires; if the target spec has been deleted/renamed, the scheduler
    logs and skips). `prompt` is the initial input passed in — for agent
    targets it becomes the agent's prompt; for workflow targets it
    becomes the chain's `{input}`.
    """
    name: str
    domain: str
    schedule: str            # raw cron expression, e.g. "*/5 * * * *"
    target_kind: str         # 'agent' | 'workflow'
    target: str              # name of the target spec
    prompt: str              # initial input for the fired run
    description: str         # markdown body shown in the modal
    spec_path: Path
    spec_hash: str

    def to_summary(self) -> dict:
        """Listing dict; the route merges this with trigger_state."""
        return {
            "kind": "trigger",
            "name": self.name,
            "domain": self.domain,
            "schedule": self.schedule,
            "target_kind": self.target_kind,
            "target": self.target,
            "prompt": self.prompt,
            "spec_hash": self.spec_hash,
        }


@dataclass
class ServiceSpec:
    """A long-lived systemd service surfaced as a fleet card (Phase 7).

    Spec files in `means/agents/specs/services/<name>.md` declare
    `kind: service` in frontmatter. Unlike AgentSpec these aren't spawned
    on demand — they're already running. The runtime helper queries
    systemctl/journalctl on read; we only persist the metadata here.
    """
    name: str
    domain: str
    unit: str               # full systemd unit name with suffix (.service / .timer)
    scope: str              # 'user' or 'system' (only 'user' wired in Phase 7)
    purpose: str            # one-liner shown on the card
    description: str        # markdown body, shown in the modal
    spec_path: Path
    spec_hash: str

    def to_summary(self) -> dict:
        """Dict for GET /services listing. Status is merged in by the route."""
        return {
            "kind": "service",
            "name": self.name,
            "domain": self.domain,
            "unit": self.unit,
            "scope": self.scope,
            "purpose": self.purpose,
            "spec_hash": self.spec_hash,
        }
