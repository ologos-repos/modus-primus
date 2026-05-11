"""Tests for runtime/workflow_daemon.run_workflow.

The workflow daemon polls child runs to terminal state via `sleep_fn`,
so we drive step completion through a fake sleep that advances the
oldest-pending child by one transition per call. spawn_fn is a no-op
(returns _FakeProc) — we don't want to actually launch any subprocess
and we can't synchronously mark the run done in spawn_fn because
launch_daemon would clobber the status to 'pending' on return.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from means.agents.runtime.store import RunStore
from means.agents.runtime.workflow_daemon import run_workflow


# ---------- helpers ----------


def _write_agent(root: Path, name: str, body: str = "agent body") -> None:
    p = root / f"{name}.md"
    p.write_text(f"---\nfork: dev\nmodel: m\n---\n{body}")


def _write_workflow(root: Path, name: str, content: str) -> None:
    p = root / f"{name}.md"
    p.write_text(content)


class _FakeProc:
    def __init__(self, pid: int = 99999):
        self.pid = pid


def _no_op_spawn(_cmd, _cwd):
    return _FakeProc()


class _StepDriver:
    """Sleep_fn that completes the next pending child on each poll cycle.
    `outputs` is a list of (text_output, terminal_status) tuples — one per
    step. Default terminal_status is 'done'."""

    def __init__(self, store: RunStore, outputs: list):
        self.store = store
        self.outputs = list(outputs)
        self.idx = 0

    def __call__(self, _interval_s: float) -> None:
        if self.idx >= len(self.outputs):
            return
        with self.store._connect() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT run_id FROM runs WHERE status='pending' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return
        run_id = row[0]
        entry = self.outputs[self.idx]
        self.idx += 1
        if isinstance(entry, tuple):
            text, status = entry
        else:
            text, status = entry, "done"
        if text:
            self.store.append_event(run_id, "token", {"text": text})
        if status == "done":
            self.store.update_status(run_id, "done", exit_code=0)
        elif status == "error":
            self.store.update_status(run_id, "error", error=text or "step failed")
        else:
            self.store.update_status(run_id, status, exit_code=-1)


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "agents.sqlite")


@pytest.fixture
def specs_root(tmp_path: Path) -> Path:
    root = tmp_path / "specs"
    root.mkdir()
    _write_agent(root, "step-a")
    _write_agent(root, "step-b")
    _write_agent(root, "step-c")
    return root


def _workflow_hash(specs_root: Path, name: str) -> str:
    from means.agents.specs.loader import find_workflow_spec
    spec = find_workflow_spec(specs_root, name)
    return spec.spec_hash


# ---------- happy path ----------


def test_workflow_runs_steps_sequentially_and_threads_prev_output(
    store: RunStore, specs_root: Path,
):
    _write_workflow(specs_root, "chain", (
        "---\nkind: workflow\nsteps:\n"
        "  - id: a\n    agent: step-a\n    prompt: \"first: {input}\"\n"
        "  - id: b\n    agent: step-b\n    prompt: \"second on: {prev_output}\"\n"
        "  - id: c\n    agent: step-c\n    prompt: \"third on: {prev_output}\"\n"
        "---\nbody"
    ))
    wr = store.create_workflow_run(
        workflow_name="chain", spec_hash=_workflow_hash(specs_root, "chain"),
        prompt="initial input",
    )
    driver = _StepDriver(store, ["alpha-out", "beta-out", "gamma-out"])

    rc = run_workflow(
        wr.workflow_run_id, store.db_path,
        specs_root=specs_root,
        spawn_fn=_no_op_spawn,
        sleep_fn=driver,
    )
    assert rc == 0

    fetched = store.get_workflow_run(wr.workflow_run_id)
    assert fetched.status == "done"
    assert fetched.final_output == "gamma-out"
    assert fetched.error is None

    children = store.list_runs_for_workflow(wr.workflow_run_id)
    names = [c.agent_name for c in children]
    assert names == ["step-a", "step-b", "step-c"]
    # Each child's prompt was rendered correctly with prev_output threading.
    assert children[0].prompt == "first: initial input"
    assert children[1].prompt == "second on: alpha-out"
    assert children[2].prompt == "third on: beta-out"


def test_workflow_marks_running_then_done(store: RunStore, specs_root: Path):
    _write_workflow(specs_root, "tiny", (
        "---\nkind: workflow\nsteps:\n"
        "  - agent: step-a\n    prompt: hi\n"
        "---\nbody"
    ))
    wr = store.create_workflow_run(
        workflow_name="tiny", spec_hash=_workflow_hash(specs_root, "tiny"),
        prompt="x",
    )
    driver = _StepDriver(store, ["only output"])

    run_workflow(
        wr.workflow_run_id, store.db_path,
        specs_root=specs_root, spawn_fn=_no_op_spawn, sleep_fn=driver,
    )

    final = store.get_workflow_run(wr.workflow_run_id)
    assert final.status == "done"
    assert final.completed_at is not None  # auto-stamped
    assert final.final_output == "only output"


# ---------- failure paths ----------


def test_workflow_short_circuits_on_step_failure(
    store: RunStore, specs_root: Path,
):
    """Step b errors → workflow lands in error and step c never runs."""
    _write_workflow(specs_root, "chain", (
        "---\nkind: workflow\nsteps:\n"
        "  - id: a\n    agent: step-a\n    prompt: ok\n"
        "  - id: b\n    agent: step-b\n    prompt: \"{prev_output}\"\n"
        "  - id: c\n    agent: step-c\n    prompt: \"{prev_output}\"\n"
        "---\nbody"
    ))
    wr = store.create_workflow_run(
        workflow_name="chain", spec_hash=_workflow_hash(specs_root, "chain"),
        prompt="x",
    )
    driver = _StepDriver(store, [
        ("alpha", "done"),
        ("bad input", "error"),
    ])

    rc = run_workflow(
        wr.workflow_run_id, store.db_path,
        specs_root=specs_root, spawn_fn=_no_op_spawn, sleep_fn=driver,
    )
    assert rc == 4

    final = store.get_workflow_run(wr.workflow_run_id)
    assert final.status == "error"
    assert "step 'b'" in final.error
    assert "bad input" in final.error
    children = store.list_runs_for_workflow(wr.workflow_run_id)
    assert [c.agent_name for c in children] == ["step-a", "step-b"]


def test_workflow_with_unknown_agent_lands_in_error(
    store: RunStore, specs_root: Path,
):
    """A workflow referencing an agent that doesn't exist fails up front,
    before spawning anything."""
    _write_workflow(specs_root, "ghost-chain", (
        "---\nkind: workflow\nsteps:\n"
        "  - agent: ghost-agent\n    prompt: hi\n"
        "---\nbody"
    ))
    wr = store.create_workflow_run(
        workflow_name="ghost-chain",
        spec_hash=_workflow_hash(specs_root, "ghost-chain"),
        prompt="x",
    )

    spawned: list = []
    def driver(cmd, cwd):
        spawned.append(cmd)
        return _FakeProc()

    rc = run_workflow(
        wr.workflow_run_id, store.db_path,
        specs_root=specs_root, spawn_fn=driver, sleep_fn=lambda _s: None,
    )
    assert rc == 3

    final = store.get_workflow_run(wr.workflow_run_id)
    assert final.status == "error"
    assert "ghost-agent" in final.error
    assert spawned == []


def test_workflow_unknown_id_returns_2(store: RunStore, specs_root: Path):
    rc = run_workflow(
        "ghost-id", store.db_path,
        specs_root=specs_root, spawn_fn=_no_op_spawn,
        sleep_fn=lambda _s: None,
    )
    assert rc == 2


def test_workflow_spec_hash_mismatch(store: RunStore, specs_root: Path):
    """If the workflow spec changes between queue and execution, the
    daemon refuses to run with a clean error."""
    _write_workflow(specs_root, "x", (
        "---\nkind: workflow\nsteps:\n"
        "  - agent: step-a\n    prompt: hi\n"
        "---\nbody"
    ))
    wr = store.create_workflow_run(
        workflow_name="x", spec_hash="OUTDATED-HASH", prompt="p",
    )
    rc = run_workflow(
        wr.workflow_run_id, store.db_path,
        specs_root=specs_root, spawn_fn=_no_op_spawn,
        sleep_fn=lambda _s: None,
    )
    assert rc == 2
    final = store.get_workflow_run(wr.workflow_run_id)
    assert final.status == "error"
    assert "spec hash mismatch" in final.error
