"""RunStore — SQLite-backed persistence for agent runs and their events.

Schema (means/agents/schema.sql) is applied on init; subsequent inits are
idempotent. A single SQLite file at means/agents/data/agents.sqlite (or
wherever the caller points) holds everything; WAL mode is enabled for
concurrent readers + writer.

Sync API. The aiohttp routes layer wraps calls in `asyncio.to_thread()`
where needed (Phase 1 traffic is single-user; SQLite calls are fast enough
that contention isn't a concern). aiosqlite is in requirements but kept
optional — switch to it in a later phase if profiling shows the to_thread
hop is hot.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"


def new_run_id() -> str:
    """Sortable run id: <epoch_ms>-<short_uuid>."""
    return f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"


@dataclass
class Run:
    run_id: str
    agent_name: str
    spec_hash: str
    fork: str
    status: str  # pending|running|done|error|cancelled
    started_at: float
    completed_at: Optional[float]
    exit_code: Optional[int]
    prompt: str
    cost_usd: float
    parent_session_id: Optional[str]
    parent_turn_id: Optional[str]
    pid: Optional[int]
    error: Optional[str]
    # Phase 3 — QA pass outcome (null = QA skipped, no spec.qa.criteria)
    qa_outcome: Optional[str] = None    # pass | fail | error
    qa_reason: Optional[str] = None
    # Phase 8 — set when this run is a child step of a workflow execution.
    # Used by /workflow-runs/{id} to enumerate the chain's child runs.
    parent_workflow_run_id: Optional[str] = None
    # Phase 9 — set when this run was spawned by a scheduled trigger.
    triggered_by: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "agent_name": self.agent_name,
            "spec_hash": self.spec_hash,
            "fork": self.fork,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "exit_code": self.exit_code,
            "prompt": self.prompt,
            "cost_usd": self.cost_usd,
            "parent_session_id": self.parent_session_id,
            "parent_turn_id": self.parent_turn_id,
            "pid": self.pid,
            "error": self.error,
            "qa_outcome": self.qa_outcome,
            "qa_reason": self.qa_reason,
            "parent_workflow_run_id": self.parent_workflow_run_id,
            "triggered_by": self.triggered_by,
        }


@dataclass
class WorkflowRun:
    """Phase 8: linear-chain workflow execution. Mirrors Run's status shape
    so the UI's polling logic can treat both alike. Steps are normal `runs`
    rows linked back via parent_workflow_run_id."""
    workflow_run_id: str
    workflow_name: str
    spec_hash: str
    status: str  # pending|running|done|error|cancelled
    started_at: float
    completed_at: Optional[float]
    prompt: str               # initial {input} for the chain
    final_output: Optional[str]
    error: Optional[str]
    pid: Optional[int]
    # Phase 9 — set when this workflow run was spawned by a scheduled trigger.
    triggered_by: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "workflow_run_id": self.workflow_run_id,
            "workflow_name": self.workflow_name,
            "spec_hash": self.spec_hash,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "prompt": self.prompt,
            "final_output": self.final_output,
            "error": self.error,
            "pid": self.pid,
            "triggered_by": self.triggered_by,
        }


@dataclass
class Event:
    run_id: str
    seq: int
    ts: float
    type: str
    data: dict

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "type": self.type,
            "data": self.data,
        }


@dataclass
class TriggerState:
    """Phase 9: persisted per-trigger state. The trigger spec lives in
    the filesystem; this row tracks last_fired_at + fire_count so the
    scheduler picks up cleanly across restarts."""
    name: str
    last_fired_at: Optional[float]
    fire_count: int


_TERMINAL_STATUSES = ("done", "error", "cancelled")


class RunStore:
    """SQLite-backed persistence for agent runs and their event logs."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ---- internals ----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            isolation_level=None,  # autocommit
            check_same_thread=False,
            timeout=10.0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        schema_sql = SCHEMA_PATH.read_text()
        with self._connect() as conn:
            conn.executescript(schema_sql)
            # Idempotent migrations for in-place upgrades. CREATE TABLE IF NOT
            # EXISTS skips an existing table — but new columns won't appear.
            # Each ALTER below is wrapped in try/except: if the column already
            # exists (fresh DB or already-migrated), sqlite raises
            # OperationalError which we swallow.
            for migration in (
                "ALTER TABLE runs ADD COLUMN qa_outcome TEXT",   # Phase 3
                "ALTER TABLE runs ADD COLUMN qa_reason TEXT",    # Phase 3
                "ALTER TABLE runs ADD COLUMN parent_workflow_run_id TEXT",  # Phase 8
                "ALTER TABLE runs ADD COLUMN triggered_by TEXT",  # Phase 9
                "ALTER TABLE workflow_runs ADD COLUMN triggered_by TEXT",  # Phase 9
            ):
                try:
                    conn.execute(migration)
                except sqlite3.OperationalError:
                    pass  # column already exists

    # ---- runs ----

    def create_run(
        self,
        *,
        agent_name: str,
        spec_hash: str,
        fork: str,
        prompt: str,
        parent_session_id: Optional[str] = None,
        parent_turn_id: Optional[str] = None,
        parent_workflow_run_id: Optional[str] = None,
        triggered_by: Optional[str] = None,
    ) -> Run:
        run_id = new_run_id()
        started_at = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO runs
                       (run_id, agent_name, spec_hash, fork, status, started_at,
                        prompt, parent_session_id, parent_turn_id,
                        parent_workflow_run_id, triggered_by)
                   VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, agent_name, spec_hash, fork, started_at,
                    prompt, parent_session_id, parent_turn_id,
                    parent_workflow_run_id, triggered_by,
                ),
            )
        run = self.get_run(run_id)
        assert run is not None
        return run

    def update_status(
        self,
        run_id: str,
        status: str,
        *,
        completed_at: Optional[float] = None,
        exit_code: Optional[int] = None,
        cost_usd: Optional[float] = None,
        pid: Optional[int] = None,
        error: Optional[str] = None,
        qa_outcome: Optional[str] = None,
        qa_reason: Optional[str] = None,
    ) -> None:
        """Patch-style update. Only fields explicitly passed are written.
        Auto-stamps completed_at when status transitions to a terminal value
        and the caller didn't pass one."""
        sets: list[str] = ["status = ?"]
        values: list = [status]
        if status in _TERMINAL_STATUSES and completed_at is None:
            completed_at = time.time()
        if completed_at is not None:
            sets.append("completed_at = ?")
            values.append(completed_at)
        if exit_code is not None:
            sets.append("exit_code = ?")
            values.append(exit_code)
        if cost_usd is not None:
            sets.append("cost_usd = ?")
            values.append(cost_usd)
        if pid is not None:
            sets.append("pid = ?")
            values.append(pid)
        if error is not None:
            sets.append("error = ?")
            values.append(error)
        if qa_outcome is not None:
            sets.append("qa_outcome = ?")
            values.append(qa_outcome)
        if qa_reason is not None:
            sets.append("qa_reason = ?")
            values.append(qa_reason)
        values.append(run_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE runs SET {', '.join(sets)} WHERE run_id = ?",
                values,
            )

    def get_run(self, run_id: str) -> Optional[Run]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return _row_to_run(row) if row else None

    def list_runs(
        self,
        *,
        agent_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
        top_level_only: bool = False,
    ) -> list[Run]:
        """List runs. With `top_level_only=True` (Phase 8) excludes runs
        that are children of a workflow execution — the UI surfaces those
        through the workflow-run modal instead, avoiding duplication."""
        clauses: list[str] = []
        values: list = []
        if agent_name is not None:
            clauses.append("agent_name = ?")
            values.append(agent_name)
        if status is not None:
            clauses.append("status = ?")
            values.append(status)
        if top_level_only:
            clauses.append("parent_workflow_run_id IS NULL")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT * FROM runs {where} "
            "ORDER BY started_at DESC LIMIT ?"
        )
        values.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, values).fetchall()
        return [_row_to_run(row) for row in rows]

    # ---- events ----

    def append_event(self, run_id: str, type: str, data: dict) -> int:
        """Append an event; returns the assigned seq (monotonic per run).

        Uses a transaction with `BEGIN IMMEDIATE` so concurrent appenders
        serialize on the seq computation rather than racing for the same seq.
        """
        ts = time.time()
        data_json = json.dumps(data, separators=(",", ":"))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), -1) + 1 FROM events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                seq = row[0]
                conn.execute(
                    "INSERT INTO events (run_id, seq, ts, type, data) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (run_id, seq, ts, type, data_json),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return seq

    def get_events(
        self, run_id: str, *, from_seq: int = 0
    ) -> list[Event]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq >= ? "
                "ORDER BY seq ASC",
                (run_id, from_seq),
            ).fetchall()
        return [_row_to_event(row) for row in rows]

    def event_count(self, run_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE run_id = ?", (run_id,)
            ).fetchone()
        return int(row[0])

    # ---- workflow runs (Phase 8) ----

    def create_workflow_run(
        self, *, workflow_name: str, spec_hash: str, prompt: str,
        triggered_by: Optional[str] = None,
    ) -> WorkflowRun:
        wf_run_id = new_run_id()
        started_at = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO workflow_runs
                       (workflow_run_id, workflow_name, spec_hash, status,
                        started_at, prompt, triggered_by)
                   VALUES (?, ?, ?, 'pending', ?, ?, ?)""",
                (wf_run_id, workflow_name, spec_hash, started_at, prompt,
                 triggered_by),
            )
        wr = self.get_workflow_run(wf_run_id)
        assert wr is not None
        return wr

    def update_workflow_status(
        self,
        workflow_run_id: str,
        status: str,
        *,
        completed_at: Optional[float] = None,
        final_output: Optional[str] = None,
        error: Optional[str] = None,
        pid: Optional[int] = None,
    ) -> None:
        sets: list[str] = ["status = ?"]
        values: list = [status]
        if status in _TERMINAL_STATUSES and completed_at is None:
            completed_at = time.time()
        if completed_at is not None:
            sets.append("completed_at = ?")
            values.append(completed_at)
        if final_output is not None:
            sets.append("final_output = ?")
            values.append(final_output)
        if error is not None:
            sets.append("error = ?")
            values.append(error)
        if pid is not None:
            sets.append("pid = ?")
            values.append(pid)
        values.append(workflow_run_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE workflow_runs SET {', '.join(sets)} "
                f"WHERE workflow_run_id = ?",
                values,
            )

    def get_workflow_run(self, workflow_run_id: str) -> Optional[WorkflowRun]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE workflow_run_id = ?",
                (workflow_run_id,),
            ).fetchone()
        return _row_to_workflow_run(row) if row else None

    def list_workflow_runs(self, limit: int = 10) -> list[WorkflowRun]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_workflow_run(row) for row in rows]

    def list_runs_for_workflow(
        self, workflow_run_id: str
    ) -> list[Run]:
        """Child runs of a workflow, in start order. Used by the workflow
        modal to render the step list."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE parent_workflow_run_id = ? "
                "ORDER BY started_at ASC",
                (workflow_run_id,),
            ).fetchall()
        return [_row_to_run(row) for row in rows]

    # ---- trigger state (Phase 9) ----

    def get_trigger_state(self, name: str) -> Optional["TriggerState"]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM trigger_state WHERE name = ?", (name,),
            ).fetchone()
        if row is None:
            return None
        return TriggerState(
            name=row["name"],
            last_fired_at=row["last_fired_at"],
            fire_count=int(row["fire_count"] or 0),
        )

    def record_trigger_fire(self, name: str, fired_at: float) -> None:
        """Upsert trigger_state, incrementing fire_count. Called by the
        scheduler after a successful fire and by the manual fire route."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO trigger_state (name, last_fired_at, fire_count)
                   VALUES (?, ?, 1)
                   ON CONFLICT(name) DO UPDATE SET
                       last_fired_at = excluded.last_fired_at,
                       fire_count = trigger_state.fire_count + 1""",
                (name, fired_at),
            )


# ---- row → dataclass converters ----


def _row_to_run(row: sqlite3.Row) -> Run:
    # `qa_outcome` / `qa_reason` are Phase-3 columns; defensive `.keys()` check
    # so this still works against a not-yet-migrated DB during transition.
    keys = row.keys()
    return Run(
        run_id=row["run_id"],
        agent_name=row["agent_name"],
        spec_hash=row["spec_hash"],
        fork=row["fork"],
        status=row["status"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        exit_code=row["exit_code"],
        prompt=row["prompt"],
        cost_usd=row["cost_usd"] or 0.0,
        parent_session_id=row["parent_session_id"],
        parent_turn_id=row["parent_turn_id"],
        pid=row["pid"],
        error=row["error"],
        qa_outcome=row["qa_outcome"] if "qa_outcome" in keys else None,
        qa_reason=row["qa_reason"] if "qa_reason" in keys else None,
        parent_workflow_run_id=(
            row["parent_workflow_run_id"]
            if "parent_workflow_run_id" in keys else None
        ),
        triggered_by=row["triggered_by"] if "triggered_by" in keys else None,
    )


def _row_to_workflow_run(row: sqlite3.Row) -> WorkflowRun:
    keys = row.keys()
    return WorkflowRun(
        workflow_run_id=row["workflow_run_id"],
        workflow_name=row["workflow_name"],
        spec_hash=row["spec_hash"],
        status=row["status"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        prompt=row["prompt"],
        final_output=row["final_output"],
        error=row["error"],
        pid=row["pid"],
        triggered_by=row["triggered_by"] if "triggered_by" in keys else None,
    )


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        run_id=row["run_id"],
        seq=row["seq"],
        ts=row["ts"],
        type=row["type"],
        data=json.loads(row["data"]),
    )
