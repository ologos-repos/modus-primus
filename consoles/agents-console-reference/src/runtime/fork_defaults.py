"""Per-fork default tool allowlists + the universe of known tools.

`resolve_tools(spec)` is the single legitimate read site for spec.tools —
backend code goes through it. Resolution rules:

  spec.tools is None  → fork default (dev: [Read, Edit, Bash, Grep]; infraops: [])
  spec.tools is []    → [] (explicit no tools — single-shot)
  spec.tools is [...] → that exact list

`KNOWN_TOOLS` is the universe used to compute denylists from allowlists
(since `--allowedTools` in claude is auto-approve, not restrict — we use
`--disallowedTools` with the complement to actually enforce). Stale
KNOWN_TOOLS = a newly-shipped [ENTERPRISE: cognitive engine CLI] tool slips past the denylist;
acceptable for Phase 1, tightened by Phase 4 approval gates.
"""
from __future__ import annotations

from .. specs.model import AgentSpec


_FORK_DEFAULTS: dict[str, list[str]] = {
    "dev": ["Read", "Edit", "Bash", "Grep"],
    # Phase 5: infraops defaults to read-only inspection tools. Bash is
    # included (unrestricted) because claude's `Bash(pattern)` permission
    # syntax is bypassed by --dangerously-skip-permissions, which we need
    # for headless runs. Security boundary is the approval gate +
    # audit trail (Phase 4 makes requires_approval mandatory for infraops),
    # not pattern restriction. JD reviews each prompt before approving.
    "infraops": ["Read", "Bash", "Grep"],
}


# Snapshot of [ENTERPRISE: cognitive engine CLI] 2.1.x built-in tool names. Used to compute
# denylists (KNOWN_TOOLS - allowed). MCP tools (mcp__*) intentionally
# excluded — they need auth and aren't in scope for agents.
KNOWN_TOOLS: frozenset[str] = frozenset({
    "AskUserQuestion",
    "Bash",
    "CronCreate",
    "CronDelete",
    "CronList",
    "Edit",
    "EnterPlanMode",
    "EnterWorktree",
    "ExitPlanMode",
    "ExitWorktree",
    "Glob",
    "Grep",
    "Monitor",
    "NotebookEdit",
    "PushNotification",
    "Read",
    "RemoteTrigger",
    "ScheduleWakeup",
    "Skill",
    "Task",
    "TaskOutput",
    "TaskStop",
    "TodoWrite",
    "ToolSearch",
    "WebFetch",
    "WebSearch",
    "Write",
})


def resolve_tools(spec: AgentSpec) -> list[str]:
    """Return the effective tool allowlist for `spec`."""
    if spec.tools is not None:
        return list(spec.tools)
    return list(_FORK_DEFAULTS.get(spec.fork, []))


def disallowed_for(allowed: list[str]) -> list[str]:
    """Return the complement of `allowed` against KNOWN_TOOLS.

    Used by ClaudeCliBackend to build `--disallowedTools` so claude
    actually drops the un-allowed tools from the agent's set rather
    than just auto-approving them on the way through.
    """
    return sorted(KNOWN_TOOLS - set(allowed))
