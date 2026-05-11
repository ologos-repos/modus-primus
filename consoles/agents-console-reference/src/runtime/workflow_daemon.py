"""Detached workflow runner. Invoked by the /workflows/{name}/run route.

  python -m means.agents.runtime.workflow_daemon \\
      --workflow-run-id <id> --db <path>

Reads the workflow_run row + workflow spec, iterates steps sequentially,
spawns each step as a normal agent run via run.spawn (with
parent_workflow_run_id set), and polls each child to terminal status
before kicking the next. The previous step's text output (token events
concatenated) is rendered into the next step's prompt template via
{prev_output}.

Phase 8 ships linear-chain workflows only. DAGs / parallel branches /
conditionals are deferred. The workflow daemon stays a single Python
process for simplicity — child agent runs are themselves detached
daemons, so this process's job is just polling + threading state.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from ..specs.loader import find_workflow_spec
from ..specs.model import WorkflowSpec
from . import run as run_module
from .store import Run, RunStore, WorkflowRun
from .workflow_runner import extract_text_output, render_prompt


_DEFAULT_SPECS_ROOT = Path(__file__).resolve().parent.parent / "specs"

# Polling cadence: 0.5s while a child step is pending or running.
_POLL_INTERVAL_S = 0.5

# Terminal statuses we should stop polling on.
_CHILD_TERMINAL = ("done", "error", "cancelled")
# Approval-pending isn't terminal — keep polling so a human approve→done
# transition doesn't strand the workflow.


def run_workflow(
    workflow_run_id: str,
    db_path: Path,
    *,
    specs_root: Path = _DEFAULT_SPECS_ROOT,
    spawn_fn: Optional[Callable] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    poll_interval_s: float = _POLL_INTERVAL_S,
) -> int:
    """Execute the workflow identified by `workflow_run_id`. Returns an
    exit code. spawn_fn / sleep_fn are injectable so tests can drive the
    daemon without subprocesses or wall-clock waits.
    """
    store = RunStore(db_path)
    wr = store.get_workflow_run(workflow_run_id)
    if wr is None:
        sys.stderr.write(f"workflow_daemon: run {workflow_run_id!r} not found\n")
        return 2

    try:
        spec = find_workflow_spec(specs_root, wr.workflow_name)
        if spec is None:
            store.update_workflow_status(
                workflow_run_id, "error",
                error=f"workflow spec not found: {wr.workflow_name!r}",
            )
            return 2
        if spec.spec_hash != wr.spec_hash:
            store.update_workflow_status(
                workflow_run_id, "error",
                error="spec hash mismatch — workflow spec changed since queued",
            )
            return 2

        store.update_workflow_status(workflow_run_id, "running")
        prev_output = ""

        for step in spec.steps:
            prompt = render_prompt(
                step.prompt, input=wr.prompt, prev_output=prev_output,
            )
            kwargs: dict = {
                "store": store,
                "agent_name": step.agent,
                "spec_hash": _resolve_agent_spec_hash(specs_root, step.agent),
                "fork": _resolve_agent_fork(specs_root, step.agent),
                "prompt": prompt,
                "parent_workflow_run_id": workflow_run_id,
            }
            if spawn_fn is not None:
                kwargs["spawn_fn"] = spawn_fn

            child_spec_hash = kwargs["spec_hash"]
            child_fork = kwargs["fork"]
            if child_spec_hash is None or child_fork is None:
                store.update_workflow_status(
                    workflow_run_id, "error",
                    error=f"step {step.id!r} references unknown agent {step.agent!r}",
                )
                return 3

            child = run_module.spawn(**kwargs)
            terminal_status = _await_child_terminal(
                store, child.run_id, sleep_fn, poll_interval_s,
            )

            if terminal_status != "done":
                child_row = store.get_run(child.run_id)
                err = (child_row.error if child_row else None) \
                    or (child_row.qa_reason if child_row else None) \
                    or terminal_status
                store.update_workflow_status(
                    workflow_run_id, "error",
                    error=f"step {step.id!r} ended in {terminal_status}: {err}",
                )
                return 4

            events = store.get_events(child.run_id)
            prev_output = extract_text_output(events)

        store.update_workflow_status(
            workflow_run_id, "done", final_output=prev_output,
        )
        return 0

    except Exception as exc:  # pragma: no cover (logged + persisted below)
        logging.exception("workflow_daemon: %s failed", workflow_run_id)
        store.update_workflow_status(
            workflow_run_id, "error", error=str(exc),
        )
        return 1


def _resolve_agent_spec_hash(specs_root: Path, agent_name: str) -> Optional[str]:
    from ..specs.loader import find_spec
    spec = find_spec(specs_root, agent_name)
    return spec.spec_hash if spec else None


def _resolve_agent_fork(specs_root: Path, agent_name: str) -> Optional[str]:
    from ..specs.loader import find_spec
    spec = find_spec(specs_root, agent_name)
    return spec.fork if spec else None


def _await_child_terminal(
    store: RunStore,
    run_id: str,
    sleep_fn: Callable[[float], None],
    interval_s: float,
) -> str:
    """Poll the runs row until status is terminal. Returns the final status."""
    while True:
        row = store.get_run(run_id)
        if row is None:
            return "error"  # row vanished — treat as failure
        if row.status in _CHILD_TERMINAL:
            return row.status
        sleep_fn(interval_s)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args()
    code = run_workflow(args.workflow_run_id, args.db)
    sys.exit(code)


if __name__ == "__main__":
    main()
