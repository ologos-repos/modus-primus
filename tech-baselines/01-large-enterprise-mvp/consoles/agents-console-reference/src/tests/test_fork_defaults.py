"""Tests for runtime/fork_defaults — resolve_tools + disallowed_for."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from means.agents.runtime.fork_defaults import (
    KNOWN_TOOLS,
    disallowed_for,
    resolve_tools,
)
from means.agents.specs.model import AgentSpec


def _spec(*, fork: str = "dev", tools: Optional[list[str]] = None) -> AgentSpec:
    return AgentSpec(
        name="x", domain="", fork=fork,
        model="sonnet", system_prompt="",
        timeout_s=60, tools=tools, qa={}, cwd=None, requires_approval=False,
        spec_path=Path("/x.md"), spec_hash="h",
    )


# ---------- resolve_tools ----------


def test_resolve_dev_default():
    """Dev fork with tools=None → [Read, Edit, Bash, Grep]."""
    assert resolve_tools(_spec(fork="dev", tools=None)) == [
        "Read", "Edit", "Bash", "Grep",
    ]


def test_resolve_infraops_defaults():
    """Phase 5: infraops gets read-only-leaning defaults (Read, Bash, Grep).
    Bash is unrestricted because claude's pattern syntax is bypassed by
    --dangerously-skip-permissions; security comes from the approval gate."""
    assert resolve_tools(_spec(fork="infraops", tools=None)) == [
        "Read", "Bash", "Grep",
    ]


def test_resolve_explicit_empty_overrides_default():
    """tools=[] means no tools, even on dev fork."""
    assert resolve_tools(_spec(fork="dev", tools=[])) == []


def test_resolve_explicit_list_overrides_default():
    """tools=['Read'] means just Read, regardless of fork."""
    assert resolve_tools(_spec(fork="dev", tools=["Read"])) == ["Read"]
    assert resolve_tools(_spec(fork="infraops", tools=["Read"])) == ["Read"]


def test_resolve_unknown_fork_returns_empty():
    """Future-fork-name with tools=None → [] (no behavior leaks)."""
    assert resolve_tools(_spec(fork="madeup", tools=None)) == []


def test_resolve_returns_independent_list():
    """Multiple resolves don't share a mutable list."""
    a = resolve_tools(_spec(fork="dev", tools=None))
    b = resolve_tools(_spec(fork="dev", tools=None))
    a.append("MUTANT")
    assert "MUTANT" not in b


# ---------- disallowed_for ----------


def test_disallowed_complement_full():
    """Empty allowlist → all KNOWN_TOOLS go in the denylist."""
    deny = disallowed_for([])
    assert set(deny) == set(KNOWN_TOOLS)


def test_disallowed_excludes_allowlisted():
    """Read in allowlist → Read NOT in denylist."""
    deny = disallowed_for(["Read"])
    assert "Read" not in deny
    assert "Bash" in deny  # still denied


def test_disallowed_returns_sorted():
    """Stable order helps test snapshots and CLI arg dedup."""
    deny = disallowed_for(["Read"])
    assert deny == sorted(deny)


def test_disallowed_unknown_tools_dont_appear():
    """Allowlisting a tool not in KNOWN_TOOLS doesn't poison the result."""
    deny = disallowed_for(["NotARealTool"])
    assert "NotARealTool" not in deny
    # Real tools all still denied
    assert set(deny) == set(KNOWN_TOOLS)


def test_known_tools_includes_phase1_dev_defaults():
    """Sanity check: KNOWN_TOOLS covers the dev fork defaults so they're
    actually resolvable through to claude."""
    for name in ("Read", "Edit", "Bash", "Grep"):
        assert name in KNOWN_TOOLS
