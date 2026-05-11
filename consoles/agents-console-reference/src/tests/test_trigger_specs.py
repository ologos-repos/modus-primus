"""Tests for TriggerSpec + load_trigger_spec / list_trigger_specs (Phase 9)."""
from __future__ import annotations

from pathlib import Path

import pytest

from means.agents.specs.loader import (
    find_trigger_spec,
    list_service_specs,
    list_specs,
    list_trigger_specs,
    list_workflow_specs,
    load_service_spec,
    load_spec,
    load_trigger_spec,
    load_workflow_spec,
)


_MINIMAL = (
    "---\n"
    "kind: trigger\n"
    "schedule: \"*/5 * * * *\"\n"
    "target_kind: agent\n"
    "target: hello-world\n"
    "prompt: hi there\n"
    "---\n"
    "Body description."
)


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


# ---------- load_trigger_spec ----------


def test_load_minimal_trigger(tmp_path: Path):
    p = tmp_path / "t.md"
    _write(p, _MINIMAL)
    spec = load_trigger_spec(p, root=tmp_path)
    assert spec.name == "t"
    assert spec.schedule == "*/5 * * * *"
    assert spec.target_kind == "agent"
    assert spec.target == "hello-world"
    assert spec.prompt == "hi there"
    assert spec.description == "Body description."


def test_workflow_target(tmp_path: Path):
    p = tmp_path / "t.md"
    _write(p, (
        "---\n"
        "kind: trigger\n"
        "schedule: \"0 7 * * *\"\n"
        "target_kind: workflow\n"
        "target: research-chain\n"
        "prompt: morning input\n"
        "---\nbody"
    ))
    spec = load_trigger_spec(p, root=tmp_path)
    assert spec.target_kind == "workflow"
    assert spec.target == "research-chain"


def test_missing_schedule_raises(tmp_path: Path):
    p = tmp_path / "t.md"
    _write(p, (
        "---\nkind: trigger\ntarget_kind: agent\ntarget: x\nprompt: p\n---\nbody"
    ))
    with pytest.raises(ValueError, match="schedule"):
        load_trigger_spec(p, root=tmp_path)


def test_invalid_schedule_raises_at_load_time(tmp_path: Path):
    """A bad cron expression fails-fast at load — not at scheduler tick."""
    p = tmp_path / "t.md"
    _write(p, (
        "---\nkind: trigger\nschedule: 'xxx invalid'\ntarget_kind: agent\n"
        "target: x\nprompt: p\n---\nbody"
    ))
    with pytest.raises(ValueError):
        load_trigger_spec(p, root=tmp_path)


def test_missing_target_kind_raises(tmp_path: Path):
    p = tmp_path / "t.md"
    _write(p, (
        "---\nkind: trigger\nschedule: '* * * * *'\ntarget: x\nprompt: p\n---\nbody"
    ))
    with pytest.raises(ValueError, match="target_kind"):
        load_trigger_spec(p, root=tmp_path)


def test_invalid_target_kind_raises(tmp_path: Path):
    p = tmp_path / "t.md"
    _write(p, (
        "---\nkind: trigger\nschedule: '* * * * *'\ntarget_kind: cosmic\n"
        "target: x\nprompt: p\n---\nbody"
    ))
    with pytest.raises(ValueError, match="target_kind"):
        load_trigger_spec(p, root=tmp_path)


def test_missing_target_raises(tmp_path: Path):
    p = tmp_path / "t.md"
    _write(p, (
        "---\nkind: trigger\nschedule: '* * * * *'\ntarget_kind: agent\n"
        "prompt: p\n---\nbody"
    ))
    with pytest.raises(ValueError, match="target"):
        load_trigger_spec(p, root=tmp_path)


def test_missing_prompt_raises(tmp_path: Path):
    p = tmp_path / "t.md"
    _write(p, (
        "---\nkind: trigger\nschedule: '* * * * *'\ntarget_kind: agent\n"
        "target: x\n---\nbody"
    ))
    with pytest.raises(ValueError, match="prompt"):
        load_trigger_spec(p, root=tmp_path)


# ---------- mutual exclusion across all four loaders ----------


def test_four_kinds_mutually_exclusive(tmp_path: Path):
    """Each spec lands in exactly one listing."""
    _write(tmp_path / "agent.md",
        "---\nfork: dev\nmodel: m\n---\nagent body")
    _write(tmp_path / "svc.md",
        "---\nkind: service\nunit: x.service\n---\nsvc body")
    _write(tmp_path / "wf.md", (
        "---\nkind: workflow\nsteps:\n"
        "  - agent: hello-world\n    prompt: hi\n"
        "---\nwf body"
    ))
    _write(tmp_path / "trg.md", _MINIMAL)

    agents = [s.name for s in list_specs(tmp_path)]
    services = [s.name for s in list_service_specs(tmp_path)]
    workflows = [s.name for s in list_workflow_specs(tmp_path)]
    triggers = [s.name for s in list_trigger_specs(tmp_path)]
    assert agents == ["agent"]
    assert services == ["svc"]
    assert workflows == ["wf"]
    assert triggers == ["trg"]


def test_load_spec_rejects_kind_trigger(tmp_path: Path):
    p = tmp_path / "t.md"
    _write(p, _MINIMAL)
    with pytest.raises(ValueError, match="load_trigger_spec"):
        load_spec(p, root=tmp_path)


def test_load_workflow_spec_rejects_kind_trigger(tmp_path: Path):
    p = tmp_path / "t.md"
    _write(p, _MINIMAL)
    with pytest.raises(ValueError, match="not a workflow"):
        load_workflow_spec(p, root=tmp_path)


def test_load_service_spec_rejects_kind_trigger(tmp_path: Path):
    p = tmp_path / "t.md"
    _write(p, _MINIMAL)
    with pytest.raises(ValueError, match="not a service"):
        load_service_spec(p, root=tmp_path)


# ---------- find_trigger_spec ----------


def test_find_trigger_spec_hits_and_misses(tmp_path: Path):
    _write(tmp_path / "x.md", _MINIMAL)
    found = find_trigger_spec(tmp_path, "x")
    assert found is not None and found.target == "hello-world"
    assert find_trigger_spec(tmp_path, "ghost") is None


# ---------- to_summary ----------


def test_to_summary_shape(tmp_path: Path):
    p = tmp_path / "x.md"
    _write(p, _MINIMAL)
    summary = load_trigger_spec(p, root=tmp_path).to_summary()
    assert summary["kind"] == "trigger"
    assert summary["schedule"] == "*/5 * * * *"
    assert summary["target_kind"] == "agent"
    assert summary["target"] == "hello-world"
    assert "spec_path" not in summary
    assert "description" not in summary  # detail-only
