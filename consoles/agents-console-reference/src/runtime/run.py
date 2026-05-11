"""Run.spawn() — write the run row and (optionally) Popen the detached daemon.

The daemon is a separate Python process invoked as
`python -m means.agents.runtime.daemon`, with `start_new_session=True`
so it survives console restart. Tests inject a fake `spawn_fn` to exercise
the flow without leaving zombie processes.

Phase 4 splits the launch step out of spawn:
- Default `launch=True` keeps Phase 1+2 behavior — spawn creates a
  pending row AND launches the daemon.
- Approval-gated runs call `spawn(..., launch=False,
  initial_status="awaiting_approval")` — row exists, no daemon yet.
- The approve route then calls `launch_daemon(store, run_id)` to start
  the daemon for an existing pending row.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from .store import Run, RunStore


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DAEMON_MODULE = "means.agents.runtime.daemon"


# Spawn-process function: takes (cmd, cwd) and returns something with `.pid`.
SpawnFn = Callable[[list[str], Path], object]


def _real_spawn(cmd: list[str], cwd: Path):
    return subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _build_daemon_cmd(run_id: str, db_path: Path, daemon_module: str) -> list[str]:
    return [
        sys.executable,
        "-m", daemon_module,
        "--run-id", run_id,
        "--db", str(db_path),
    ]


def launch_daemon(
    *,
    store: RunStore,
    run_id: str,
    spawn_fn: SpawnFn = _real_spawn,
    repo_root: Path = _REPO_ROOT,
    daemon_module: str = _DAEMON_MODULE,
) -> Optional[int]:
    """Popen the detached daemon for an existing run. Sets status=pending
    and records the pid. Used by spawn(launch=True) and by the approve
    route after an awaiting_approval run is approved.
    """
    cmd = _build_daemon_cmd(run_id, store.db_path, daemon_module)
    proc = spawn_fn(cmd, repo_root)
    pid = getattr(proc, "pid", None)
    store.update_status(run_id, "pending", pid=pid)
    return pid


def spawn(
    *,
    store: RunStore,
    agent_name: str,
    spec_hash: str,
    fork: str,
    prompt: str,
    parent_session_id: Optional[str] = None,
    parent_turn_id: Optional[str] = None,
    parent_workflow_run_id: Optional[str] = None,
    triggered_by: Optional[str] = None,
    spawn_fn: SpawnFn = _real_spawn,
    repo_root: Path = _REPO_ROOT,
    daemon_module: str = _DAEMON_MODULE,
    launch: bool = True,
    initial_status: str = "pending",
) -> Run:
    """Insert a run row, optionally Popen the detached daemon, return the run.

    - `launch=True` (default): create + launch (Phase 1+2 behavior).
      `initial_status` is ignored — daemon is launched, status flips to
      pending with the pid.
    - `launch=False` + `initial_status="awaiting_approval"`: create row
      but skip Popen (Phase 4 approval gating). Daemon is launched later
      via `launch_daemon()` from the approve route.
    - `parent_workflow_run_id`: Phase 8 — when this run is a child step
      of a workflow execution, link it back so the workflow modal can
      enumerate its steps.
    - `triggered_by`: Phase 9 — name of the trigger (cron-driven) that
      caused this run, surfaced in the UI as "fired from <trigger>".
    """
    run = store.create_run(
        agent_name=agent_name,
        spec_hash=spec_hash,
        fork=fork,
        prompt=prompt,
        parent_session_id=parent_session_id,
        parent_turn_id=parent_turn_id,
        parent_workflow_run_id=parent_workflow_run_id,
        triggered_by=triggered_by,
    )
    if launch:
        pid = launch_daemon(
            store=store,
            run_id=run.run_id,
            spawn_fn=spawn_fn,
            repo_root=repo_root,
            daemon_module=daemon_module,
        )
        if pid is not None:
            run.pid = pid
        return run

    # Gated path — set the requested initial status (e.g. "awaiting_approval")
    # and don't launch.
    if initial_status != "pending":
        store.update_status(run.run_id, initial_status)
    fetched = store.get_run(run.run_id)
    return fetched if fetched is not None else run
