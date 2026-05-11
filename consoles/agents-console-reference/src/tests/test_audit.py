"""Tests for runtime/audit — append-only jsonl writer."""
from __future__ import annotations

import json
from pathlib import Path

from means.agents.runtime.audit import AuditLog


def test_record_appends_jsonl(tmp_path: Path):
    log = AuditLog(tmp_path / "audit.jsonl")
    rec = log.record("run_spawned", run_id="r1", agent_name="x")
    assert rec["event"] == "run_spawned"
    assert rec["run_id"] == "r1"
    assert "ts" in rec

    raw = (tmp_path / "audit.jsonl").read_text().strip().split("\n")
    assert len(raw) == 1
    parsed = json.loads(raw[0])
    assert parsed["run_id"] == "r1"


def test_record_appends_multiple_records(tmp_path: Path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("run_spawned", run_id="r1")
    log.record("approval_decision", run_id="r1", decision="approve")
    log.record("run_completed", run_id="r1", status="done")
    records = log.read_all()
    assert [r["event"] for r in records] == [
        "run_spawned", "approval_decision", "run_completed",
    ]


def test_record_creates_parent_dir(tmp_path: Path):
    """Parent directory is auto-created on init."""
    nested = tmp_path / "a" / "b" / "c" / "audit.jsonl"
    log = AuditLog(nested)
    log.record("x", k=1)
    assert nested.exists()


def test_read_all_skips_malformed(tmp_path: Path):
    """A corrupt line shouldn't break readers."""
    p = tmp_path / "audit.jsonl"
    p.write_text(
        '{"event":"a","ts":1.0}\n'
        'this is not json\n'
        '{"event":"b","ts":2.0}\n'
    )
    log = AuditLog(p)
    records = log.read_all()
    assert [r["event"] for r in records] == ["a", "b"]


def test_read_all_empty_when_no_file(tmp_path: Path):
    log = AuditLog(tmp_path / "audit.jsonl")
    # Don't record anything — file doesn't exist yet
    assert log.read_all() == []


def test_record_serializes_complex_kwargs(tmp_path: Path):
    """default=str makes Path / etc. survive json.dumps."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("test", path=Path("/some/path"), nested={"k": [1, 2, 3]})
    rec = log.read_all()[0]
    assert rec["path"] == "/some/path"
    assert rec["nested"] == {"k": [1, 2, 3]}


def test_uses_default_path_when_none(tmp_path: Path):
    """No path → default (under runtime parent's data/audit.jsonl).
    We don't actually write to the default location in tests; just verify
    the path property resolves."""
    log = AuditLog()
    assert str(log.path).endswith("data/audit.jsonl")
