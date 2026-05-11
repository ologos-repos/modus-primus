"""Tests for runtime/store.py — RunStore SQLite persistence.

Coverage: schema init + idempotency, run CRUD, status transitions with
auto-completed_at, event append with monotonic seq, concurrent-append
serialization, listing filters + ordering, get_events from offset.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from means.agents.runtime.store import (
    Event, Run, RunStore, TriggerState, WorkflowRun, new_run_id,
)


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "agents.sqlite")


# ---------- ids ----------


def test_new_run_id_unique():
    a, b = new_run_id(), new_run_id()
    assert a != b
    assert a.split("-")[0].isdigit()


# ---------- schema ----------


def test_schema_idempotent(tmp_path: Path):
    """Re-init on the same db file is a no-op (CREATE IF NOT EXISTS)."""
    db = tmp_path / "agents.sqlite"
    RunStore(db)
    RunStore(db)  # second init should not raise


def test_schema_creates_db_parent(tmp_path: Path):
    """The parent directory is auto-created."""
    db = tmp_path / "nested" / "deep" / "agents.sqlite"
    RunStore(db)
    assert db.exists()


# ---------- runs ----------


def test_create_run_returns_pending(store: RunStore):
    run = store.create_run(
        agent_name="hello-world",
        spec_hash="a" * 64,
        fork="dev",
        prompt="hi",
    )
    assert run.status == "pending"
    assert run.agent_name == "hello-world"
    assert run.spec_hash == "a" * 64
    assert run.fork == "dev"
    assert run.prompt == "hi"
    assert run.completed_at is None
    assert run.exit_code is None
    assert run.cost_usd == 0.0
    assert run.parent_session_id is None
    assert run.error is None


def test_create_run_with_parent_chat(store: RunStore):
    run = store.create_run(
        agent_name="x",
        spec_hash="h",
        fork="dev",
        prompt="p",
        parent_session_id="sess-123",
        parent_turn_id="turn-456",
    )
    assert run.parent_session_id == "sess-123"
    assert run.parent_turn_id == "turn-456"


def test_get_run_unknown_returns_none(store: RunStore):
    assert store.get_run("does-not-exist") is None


def test_get_run_round_trip(store: RunStore):
    created = store.create_run(
        agent_name="x", spec_hash="h", fork="dev", prompt="p"
    )
    fetched = store.get_run(created.run_id)
    assert fetched is not None
    assert fetched.run_id == created.run_id


def test_run_to_dict_shape(store: RunStore):
    run = store.create_run(
        agent_name="x", spec_hash="h", fork="dev", prompt="p"
    )
    d = run.to_dict()
    expected = {
        "run_id", "agent_name", "spec_hash", "fork", "status",
        "started_at", "completed_at", "exit_code", "prompt",
        "cost_usd", "parent_session_id", "parent_turn_id",
        "pid", "error",
        "qa_outcome", "qa_reason",          # Phase 3
        "parent_workflow_run_id",            # Phase 8
        "triggered_by",                      # Phase 9
    }
    assert set(d.keys()) == expected


# ---------- status transitions ----------


def test_update_status_running(store: RunStore):
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    store.update_status(r.run_id, "running", pid=12345)
    fetched = store.get_run(r.run_id)
    assert fetched.status == "running"
    assert fetched.pid == 12345
    # Not terminal — completed_at should still be None
    assert fetched.completed_at is None


def test_update_status_done_auto_stamps_completed_at(store: RunStore):
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    store.update_status(r.run_id, "done", exit_code=0, cost_usd=0.01)
    fetched = store.get_run(r.run_id)
    assert fetched.status == "done"
    assert fetched.completed_at is not None
    assert fetched.completed_at >= r.started_at
    assert fetched.exit_code == 0
    assert fetched.cost_usd == pytest.approx(0.01)


def test_update_status_error_with_message(store: RunStore):
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    store.update_status(r.run_id, "error", error="boom", exit_code=1)
    fetched = store.get_run(r.run_id)
    assert fetched.status == "error"
    assert fetched.error == "boom"
    assert fetched.exit_code == 1
    assert fetched.completed_at is not None


def test_update_status_partial_only_writes_specified(store: RunStore):
    """Fields not passed keep their previous value."""
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    store.update_status(r.run_id, "running", pid=42)
    store.update_status(r.run_id, "running")  # no other args
    fetched = store.get_run(r.run_id)
    assert fetched.pid == 42  # not clobbered


# ---------- events ----------


def test_append_event_assigns_zero_first(store: RunStore):
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    seq = store.append_event(r.run_id, "token", {"text": "hi"})
    assert seq == 0


def test_append_event_monotonic(store: RunStore):
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    seqs = [
        store.append_event(r.run_id, "token", {"text": str(i)})
        for i in range(5)
    ]
    assert seqs == [0, 1, 2, 3, 4]


def test_event_count(store: RunStore):
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    assert store.event_count(r.run_id) == 0
    for _ in range(3):
        store.append_event(r.run_id, "token", {})
    assert store.event_count(r.run_id) == 3


def test_get_events_full(store: RunStore):
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    for i in range(3):
        store.append_event(r.run_id, "token", {"i": i})
    events = store.get_events(r.run_id)
    assert [e.seq for e in events] == [0, 1, 2]
    assert events[0].type == "token"
    assert events[0].data == {"i": 0}


def test_get_events_from_offset(store: RunStore):
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    for i in range(5):
        store.append_event(r.run_id, "token", {"i": i})
    events = store.get_events(r.run_id, from_seq=3)
    assert [e.seq for e in events] == [3, 4]


def test_get_events_unknown_run_empty(store: RunStore):
    assert store.get_events("does-not-exist") == []


def test_events_isolated_by_run_id(store: RunStore):
    a = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    b = store.create_run(agent_name="y", spec_hash="h", fork="dev", prompt="q")
    store.append_event(a.run_id, "token", {"a": 1})
    store.append_event(b.run_id, "token", {"b": 1})
    a_events = store.get_events(a.run_id)
    assert len(a_events) == 1
    assert a_events[0].data == {"a": 1}


def test_concurrent_append_serializes(store: RunStore):
    """100 threads each appending one event → unique monotonic seqs, no skips."""
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    seqs: list[int] = []
    lock = threading.Lock()

    def worker(i: int):
        seq = store.append_event(r.run_id, "token", {"i": i})
        with lock:
            seqs.append(seq)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(seqs) == list(range(100))
    assert store.event_count(r.run_id) == 100


# ---------- list_runs ----------


def test_list_runs_empty(store: RunStore):
    assert store.list_runs() == []


def test_list_runs_orders_newest_first(store: RunStore):
    a = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="1")
    b = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="2")
    c = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="3")
    runs = store.list_runs()
    # c is newest (created last), should be first
    assert [r.run_id for r in runs] == [c.run_id, b.run_id, a.run_id]


def test_list_runs_by_agent(store: RunStore):
    store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="1")
    store.create_run(agent_name="y", spec_hash="h", fork="dev", prompt="2")
    store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="3")
    runs = store.list_runs(agent_name="x")
    assert len(runs) == 2
    assert all(r.agent_name == "x" for r in runs)


def test_list_runs_by_status(store: RunStore):
    a = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="1")
    b = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="2")
    store.update_status(b.run_id, "done", exit_code=0)
    pending = store.list_runs(status="pending")
    assert len(pending) == 1
    assert pending[0].run_id == a.run_id


def test_list_runs_limit(store: RunStore):
    for i in range(15):
        store.create_run(
            agent_name="x", spec_hash="h", fork="dev", prompt=str(i)
        )
    runs = store.list_runs(limit=5)
    assert len(runs) == 5


def test_qa_outcome_persists(store: RunStore):
    """update_status accepts qa_outcome + qa_reason; round-trip preserves them."""
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    store.update_status(
        r.run_id, "done", exit_code=0,
        qa_outcome="pass", qa_reason="under 50 words",
    )
    fetched = store.get_run(r.run_id)
    assert fetched.qa_outcome == "pass"
    assert fetched.qa_reason == "under 50 words"


def test_qa_outcome_fail_with_reason(store: RunStore):
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    store.update_status(
        r.run_id, "error", exit_code=4,
        qa_outcome="fail", qa_reason="missing required keyword",
        error="qa failed: missing required keyword",
    )
    fetched = store.get_run(r.run_id)
    assert fetched.status == "error"
    assert fetched.qa_outcome == "fail"
    assert fetched.qa_reason == "missing required keyword"
    assert fetched.error == "qa failed: missing required keyword"


def test_qa_columns_default_null(store: RunStore):
    """A run without QA leaves both qa_* columns null."""
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    store.update_status(r.run_id, "done", exit_code=0)
    fetched = store.get_run(r.run_id)
    assert fetched.qa_outcome is None
    assert fetched.qa_reason is None


def test_run_to_dict_includes_qa_fields(store: RunStore):
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    store.update_status(r.run_id, "done", qa_outcome="pass", qa_reason="ok")
    d = store.get_run(r.run_id).to_dict()
    assert d["qa_outcome"] == "pass"
    assert d["qa_reason"] == "ok"


def test_qa_migration_idempotent_on_legacy_db(tmp_path: Path):
    """Pre-Phase-3 DB without qa_outcome columns: opening it via RunStore
    should ALTER ADD COLUMN gracefully, not crash. Re-opening is also fine."""
    import sqlite3 as _sq
    db = tmp_path / "legacy.sqlite"
    # Hand-roll the Phase-1 schema (no qa_outcome, no qa_reason)
    with _sq.connect(db) as conn:
        conn.executescript("""
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY, agent_name TEXT NOT NULL,
            spec_hash TEXT NOT NULL, fork TEXT NOT NULL, status TEXT NOT NULL,
            started_at REAL NOT NULL, completed_at REAL, exit_code INTEGER,
            prompt TEXT NOT NULL, cost_usd REAL DEFAULT 0,
            parent_session_id TEXT, parent_turn_id TEXT, pid INTEGER, error TEXT
        );
        CREATE TABLE events (
            run_id TEXT NOT NULL, seq INTEGER NOT NULL, ts REAL NOT NULL,
            type TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (run_id, seq)
        );
        """)
    # Insert a legacy row directly
    with _sq.connect(db) as conn:
        conn.execute(
            "INSERT INTO runs (run_id, agent_name, spec_hash, fork, status, "
            "started_at, prompt) VALUES ('legacy-1', 'old', 'h', 'dev', 'done', "
            "1.0, 'p')"
        )
        conn.commit()

    # Open via RunStore — migration runs, qa_outcome column is added
    store = RunStore(db)
    fetched = store.get_run("legacy-1")
    assert fetched is not None
    assert fetched.qa_outcome is None
    assert fetched.qa_reason is None

    # Re-opening the migrated DB is also fine
    RunStore(db)


def test_event_to_dict_shape(store: RunStore):
    r = store.create_run(agent_name="x", spec_hash="h", fork="dev", prompt="p")
    store.append_event(r.run_id, "token", {"text": "hi"})
    e = store.get_events(r.run_id)[0]
    d = e.to_dict()
    assert set(d.keys()) == {"seq", "ts", "type", "data"}
    assert d["data"] == {"text": "hi"}


# ---------- workflow runs (Phase 8) ----------


def test_create_workflow_run_pending(store: RunStore):
    wr = store.create_workflow_run(
        workflow_name="research-chain",
        spec_hash="h",
        prompt="initial input",
    )
    assert wr.status == "pending"
    assert wr.prompt == "initial input"
    assert wr.completed_at is None
    assert wr.final_output is None


def test_get_workflow_run_round_trip(store: RunStore):
    wr = store.create_workflow_run(
        workflow_name="x", spec_hash="h", prompt="p",
    )
    fetched = store.get_workflow_run(wr.workflow_run_id)
    assert fetched is not None
    assert fetched.workflow_name == "x"


def test_update_workflow_status_done_with_output(store: RunStore):
    wr = store.create_workflow_run(
        workflow_name="x", spec_hash="h", prompt="p",
    )
    store.update_workflow_status(
        wr.workflow_run_id, "done", final_output="result text"
    )
    fetched = store.get_workflow_run(wr.workflow_run_id)
    assert fetched.status == "done"
    assert fetched.final_output == "result text"
    assert fetched.completed_at is not None  # auto-stamped


def test_update_workflow_status_error(store: RunStore):
    wr = store.create_workflow_run(
        workflow_name="x", spec_hash="h", prompt="p",
    )
    store.update_workflow_status(
        wr.workflow_run_id, "error", error="step 'compress' failed"
    )
    fetched = store.get_workflow_run(wr.workflow_run_id)
    assert fetched.status == "error"
    assert "compress" in fetched.error


def test_list_workflow_runs_sorted_desc(store: RunStore):
    """Most-recent first, honors limit."""
    a = store.create_workflow_run(workflow_name="a", spec_hash="h", prompt="p")
    b = store.create_workflow_run(workflow_name="b", spec_hash="h", prompt="p")
    runs = store.list_workflow_runs(limit=10)
    # b created after a → b first
    assert runs[0].workflow_run_id == b.workflow_run_id
    assert runs[1].workflow_run_id == a.workflow_run_id

    only = store.list_workflow_runs(limit=1)
    assert len(only) == 1


def test_runs_with_parent_workflow_run_id(store: RunStore):
    wr = store.create_workflow_run(
        workflow_name="x", spec_hash="h", prompt="p",
    )
    child = store.create_run(
        agent_name="step1", spec_hash="h", fork="dev", prompt="hi",
        parent_workflow_run_id=wr.workflow_run_id,
    )
    other = store.create_run(
        agent_name="standalone", spec_hash="h", fork="dev", prompt="hi",
    )

    children = store.list_runs_for_workflow(wr.workflow_run_id)
    names = [c.agent_name for c in children]
    assert names == ["step1"]
    # The standalone run has no parent
    fetched = store.get_run(other.run_id)
    assert fetched.parent_workflow_run_id is None
    # The child knows its parent
    fetched_child = store.get_run(child.run_id)
    assert fetched_child.parent_workflow_run_id == wr.workflow_run_id


def test_workflow_run_to_dict_shape(store: RunStore):
    wr = store.create_workflow_run(
        workflow_name="x", spec_hash="h", prompt="p",
    )
    d = wr.to_dict()
    expected = {
        "workflow_run_id", "workflow_name", "spec_hash", "status",
        "started_at", "completed_at", "prompt", "final_output",
        "error", "pid",
        "triggered_by",  # Phase 9
    }
    assert set(d.keys()) == expected


# ---------- triggered_by + trigger_state (Phase 9) ----------


def test_create_run_with_triggered_by(store: RunStore):
    r = store.create_run(
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
        triggered_by="heartbeat",
    )
    fetched = store.get_run(r.run_id)
    assert fetched.triggered_by == "heartbeat"


def test_create_workflow_run_with_triggered_by(store: RunStore):
    wr = store.create_workflow_run(
        workflow_name="x", spec_hash="h", prompt="p",
        triggered_by="morning-digest",
    )
    fetched = store.get_workflow_run(wr.workflow_run_id)
    assert fetched.triggered_by == "morning-digest"


def test_record_trigger_fire_creates_then_increments(store: RunStore):
    """First fire creates the row with count=1; subsequent fires
    increment and update last_fired_at."""
    assert store.get_trigger_state("heartbeat") is None
    store.record_trigger_fire("heartbeat", 1000.0)
    s1 = store.get_trigger_state("heartbeat")
    assert s1 is not None
    assert s1.last_fired_at == 1000.0
    assert s1.fire_count == 1

    store.record_trigger_fire("heartbeat", 2000.0)
    s2 = store.get_trigger_state("heartbeat")
    assert s2.last_fired_at == 2000.0
    assert s2.fire_count == 2


def test_get_trigger_state_unknown_returns_none(store: RunStore):
    assert store.get_trigger_state("ghost") is None


def test_trigger_state_dataclass_shape():
    s = TriggerState(name="x", last_fired_at=1234.0, fire_count=5)
    assert s.name == "x"
    assert s.fire_count == 5
