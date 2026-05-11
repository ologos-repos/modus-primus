"""Tests for WorkflowSpec + load_workflow_spec / list_workflow_specs (Phase 8)."""
from __future__ import annotations

from pathlib import Path

import pytest

from means.agents.specs.loader import (
    find_workflow_spec,
    list_service_specs,
    list_specs,
    list_workflow_specs,
    load_service_spec,
    load_spec,
    load_workflow_spec,
)


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


_MINIMAL = (
    "---\n"
    "kind: workflow\n"
    "steps:\n"
    "  - id: scan\n"
    "    agent: file-reader\n"
    "    prompt: read /etc/hostname\n"
    "  - id: shorten\n"
    "    agent: concise-summary\n"
    "    prompt: \"compress: {prev_output}\"\n"
    "---\n"
    "Body description."
)


# ---------- load_workflow_spec ----------


def test_load_minimal_workflow(tmp_path: Path):
    p = tmp_path / "w.md"
    _write(p, _MINIMAL)
    spec = load_workflow_spec(p, root=tmp_path)
    assert spec.name == "w"
    assert spec.description == "Body description."
    assert len(spec.steps) == 2
    assert spec.steps[0].id == "scan"
    assert spec.steps[0].agent == "file-reader"
    assert spec.steps[1].prompt == "compress: {prev_output}"


def test_step_id_defaults_to_agent_name(tmp_path: Path):
    p = tmp_path / "w.md"
    _write(p,
        "---\nkind: workflow\nsteps:\n"
        "  - agent: hello-world\n    prompt: hi\n"
        "---\nbody"
    )
    spec = load_workflow_spec(p, root=tmp_path)
    assert spec.steps[0].id == "hello-world"


def test_missing_steps_raises(tmp_path: Path):
    p = tmp_path / "w.md"
    _write(p, "---\nkind: workflow\n---\nbody")
    with pytest.raises(ValueError, match="steps"):
        load_workflow_spec(p, root=tmp_path)


def test_empty_steps_raises(tmp_path: Path):
    p = tmp_path / "w.md"
    _write(p, "---\nkind: workflow\nsteps: []\n---\nbody")
    with pytest.raises(ValueError, match="non-empty"):
        load_workflow_spec(p, root=tmp_path)


def test_step_missing_agent_raises(tmp_path: Path):
    p = tmp_path / "w.md"
    _write(p,
        "---\nkind: workflow\nsteps:\n  - prompt: hi\n---\nbody"
    )
    with pytest.raises(ValueError, match="agent"):
        load_workflow_spec(p, root=tmp_path)


def test_step_missing_prompt_raises(tmp_path: Path):
    p = tmp_path / "w.md"
    _write(p,
        "---\nkind: workflow\nsteps:\n  - agent: hello-world\n---\nbody"
    )
    with pytest.raises(ValueError, match="prompt"):
        load_workflow_spec(p, root=tmp_path)


def test_load_workflow_rejects_non_workflow_kind(tmp_path: Path):
    p = tmp_path / "w.md"
    _write(p, "---\nfork: dev\nmodel: m\n---\nbody")
    with pytest.raises(ValueError, match="kind=workflow"):
        load_workflow_spec(p, root=tmp_path)


# ---------- mutual-exclusion across the three loaders ----------


def test_three_kinds_mutually_exclusive(tmp_path: Path):
    """One file → one listing. An agent file appears only in list_specs;
    a service file only in list_service_specs; a workflow file only in
    list_workflow_specs."""
    _write(tmp_path / "agent.md",
        "---\nfork: dev\nmodel: m\n---\nagent body")
    _write(tmp_path / "svc.md",
        "---\nkind: service\nunit: x.service\n---\nsvc body")
    _write(tmp_path / "wf.md", _MINIMAL)

    agents = [s.name for s in list_specs(tmp_path)]
    services = [s.name for s in list_service_specs(tmp_path)]
    workflows = [s.name for s in list_workflow_specs(tmp_path)]
    assert agents == ["agent"]
    assert services == ["svc"]
    assert workflows == ["wf"]


def test_load_spec_rejects_kind_workflow(tmp_path: Path):
    """load_spec on a workflow file points the caller at load_workflow_spec."""
    p = tmp_path / "w.md"
    _write(p, _MINIMAL)
    with pytest.raises(ValueError, match="load_workflow_spec"):
        load_spec(p, root=tmp_path)


def test_load_service_spec_rejects_kind_workflow(tmp_path: Path):
    """load_service_spec on a workflow file raises (kind != service)."""
    p = tmp_path / "w.md"
    _write(p, _MINIMAL)
    with pytest.raises(ValueError, match="not a service spec"):
        load_service_spec(p, root=tmp_path)


# ---------- find_workflow_spec ----------


def test_find_workflow_spec_hits_and_misses(tmp_path: Path):
    _write(tmp_path / "x.md", _MINIMAL)
    found = find_workflow_spec(tmp_path, "x")
    assert found is not None and len(found.steps) == 2
    assert find_workflow_spec(tmp_path, "ghost") is None


# ---------- to_summary / to_detail ----------


def test_to_summary_excludes_steps(tmp_path: Path):
    p = tmp_path / "w.md"
    _write(p, _MINIMAL)
    summary = load_workflow_spec(p, root=tmp_path).to_summary()
    assert summary["kind"] == "workflow"
    assert summary["step_count"] == 2
    assert "steps" not in summary  # detail-only field


def test_to_detail_includes_steps(tmp_path: Path):
    p = tmp_path / "w.md"
    _write(p, _MINIMAL)
    detail = load_workflow_spec(p, root=tmp_path).to_detail()
    assert "steps" in detail
    assert detail["steps"][0]["agent"] == "file-reader"
    assert detail["step_count"] == 2
