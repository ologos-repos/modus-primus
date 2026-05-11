"""Tests for ServiceSpec + load_service_spec / list_service_specs (Phase 7)."""
from __future__ import annotations

from pathlib import Path

import pytest

from means.agents.specs.loader import (
    find_service_spec,
    list_service_specs,
    list_specs,
    load_service_spec,
    load_spec,
)


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


# ---------- load_service_spec ----------


def test_load_minimal_service_spec(tmp_path: Path):
    p = tmp_path / "console.md"
    _write(p,
        "---\n"
        "kind: service\n"
        "unit: console.service\n"
        "purpose: agents-console control surface\n"
        "---\n"
        "Body text describing the service."
    )
    spec = load_service_spec(p, root=tmp_path)
    assert spec.name == "console"
    assert spec.unit == "console.service"
    assert spec.scope == "user"
    assert spec.purpose == "agents-console control surface"
    assert spec.description == "Body text describing the service."


def test_load_service_spec_with_scope(tmp_path: Path):
    p = tmp_path / "x.md"
    _write(p,
        "---\nkind: service\nunit: x.service\nscope: system\n---\nbody"
    )
    spec = load_service_spec(p, root=tmp_path)
    assert spec.scope == "system"


def test_load_service_spec_missing_unit_raises(tmp_path: Path):
    p = tmp_path / "x.md"
    _write(p, "---\nkind: service\n---\nbody")
    with pytest.raises(ValueError, match="unit"):
        load_service_spec(p, root=tmp_path)


def test_load_service_spec_missing_kind_raises(tmp_path: Path):
    """A file without kind=service shouldn't be loadable as a service."""
    p = tmp_path / "x.md"
    _write(p, "---\nunit: x.service\n---\nbody")
    with pytest.raises(ValueError, match="kind=service"):
        load_service_spec(p, root=tmp_path)


def test_load_service_spec_invalid_scope_raises(tmp_path: Path):
    p = tmp_path / "x.md"
    _write(p,
        "---\nkind: service\nunit: x.service\nscope: cosmic\n---\nbody"
    )
    with pytest.raises(ValueError, match="scope"):
        load_service_spec(p, root=tmp_path)


def test_load_service_spec_domain_from_subdir(tmp_path: Path):
    p = tmp_path / "services" / "x.md"
    _write(p,
        "---\nkind: service\nunit: x.service\n---\nbody"
    )
    spec = load_service_spec(p, root=tmp_path)
    assert spec.domain == "services"


# ---------- listing isolation ----------


def test_list_specs_skips_service_kind(tmp_path: Path):
    """Existing list_specs (agents) must not include kind=service files."""
    _write(tmp_path / "agent.md",
        "---\nfork: dev\nmodel: m\n---\nagent body")
    _write(tmp_path / "services" / "svc.md",
        "---\nkind: service\nunit: svc.service\n---\nsvc body")
    names = [s.name for s in list_specs(tmp_path)]
    assert names == ["agent"]


def test_list_service_specs_finds_only_service_kind(tmp_path: Path):
    _write(tmp_path / "agent.md",
        "---\nfork: dev\nmodel: m\n---\nagent body")
    _write(tmp_path / "services" / "svc.md",
        "---\nkind: service\nunit: svc.service\n---\nsvc body")
    names = [s.name for s in list_service_specs(tmp_path)]
    assert names == ["svc"]


def test_load_spec_rejects_kind_service(tmp_path: Path):
    """Direct call to load_spec on a service file raises (so list_specs
    silently skips). Errors message points the caller at load_service_spec."""
    p = tmp_path / "x.md"
    _write(p, "---\nkind: service\nunit: x.service\n---\nbody")
    with pytest.raises(ValueError, match="load_service_spec"):
        load_spec(p, root=tmp_path)


def test_find_service_spec_hits_and_misses(tmp_path: Path):
    _write(tmp_path / "x.md",
        "---\nkind: service\nunit: x.service\n---\nbody")
    found = find_service_spec(tmp_path, "x")
    assert found is not None and found.unit == "x.service"
    assert find_service_spec(tmp_path, "ghost") is None


# ---------- to_summary ----------


def test_service_spec_to_summary_shape(tmp_path: Path):
    p = tmp_path / "x.md"
    _write(p,
        "---\nkind: service\nunit: x.service\npurpose: testing\n---\nbody"
    )
    summary = load_service_spec(p, root=tmp_path).to_summary()
    assert summary["kind"] == "service"
    assert summary["unit"] == "x.service"
    assert summary["purpose"] == "testing"
    assert summary["scope"] == "user"
    assert "spec_path" not in summary  # path is internal
    assert "description" not in summary  # body lives in detail endpoint


# ---------- canonical specs (14 agents-console services + timers) ----------


def test_canonical_service_specs_load():
    """All shipped service specs parse cleanly and reference real units."""
    pkg_root = Path(__file__).parent.parent
    services_root = pkg_root / "specs"
    specs = list_service_specs(services_root)
    names = {s.name for s in specs}
    expected = {
        "console", "[ENTERPRISE: personal chat bridge service]", "[ENTERPRISE: org chat bridge service]",
        "cross-fleet-coord-watcher", "agents-console-reminder", "agents-console-rescue",
        "agents-console-gmail", "thinxs-webchat", "thinxg", "lrt-chatbot",
        "blocker-poll-timer", "comment-monitor-timer",
        "cross-fleet-coord-digest-timer", "[ENTERPRISE: org identifier]-backup-timer",
    }
    assert expected.issubset(names), f"missing: {expected - names}"


def test_canonical_service_specs_have_purpose():
    """No empty `purpose:` — that's the one-line shown on the card."""
    pkg_root = Path(__file__).parent.parent
    specs = list_service_specs(pkg_root / "specs")
    for s in specs:
        assert s.purpose, f"{s.name} has empty purpose"


def test_canonical_timer_specs_use_timer_unit():
    """Files named *-timer.md must reference a .timer unit, not .service."""
    pkg_root = Path(__file__).parent.parent
    specs = list_service_specs(pkg_root / "specs")
    for s in specs:
        if s.name.endswith("-timer"):
            assert s.unit.endswith(".timer"), (
                f"{s.name}: unit {s.unit!r} should end with .timer"
            )
