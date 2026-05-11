"""In-process scheduler for cron-driven triggers (Phase 9).

Lifecycle parallels HttpCallbackNotifier (the cross-service notifier owned
by routes.py): an async `run_loop()` ticked every 30s, started on app
startup, cancelled on cleanup. Each tick:

  1. Load all `kind: trigger` specs (filesystem rglob — cheap).
  2. For each trigger, compute next_fire_at(after=last_fired_at).
  3. If now >= next_fire_at, call fire_fn(trigger, now). Then
     record_trigger_fire(trigger.name, now) so the next tick's
     next_fire_at advances to the next cron-window.

`fire_fn` is injectable: production uses `default_fire_fn` which spawns
the target as a normal agent run or workflow run via the existing
infrastructure (with `triggered_by=trigger.name` so the UI can label
the run as scheduler-fired). Tests inject a stub.

Catch-up policy: on first sight of a trigger (no trigger_state row),
last_fired_at defaults to **scheduler-startup time** rather than 0 —
so a fresh deployment doesn't fire backlog for `0 7 * * *` daily
triggers across the entire history of the universe.

Restart-recovery: at most one fire on startup if last_fired_at is far
behind. Standard cron-like semantics.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

from ..specs.loader import (
    find_spec,
    find_workflow_spec,
    list_trigger_specs,
)
from ..specs.model import TriggerSpec
from . import run as run_module
from .cron import next_fire_at, parse_cron
from .store import RunStore


log = logging.getLogger(__name__)


# `fire_fn` signature: (trigger_spec, now_epoch) -> awaitable
FireFn = Callable[[TriggerSpec, float], Awaitable[None]]


class Scheduler:
    def __init__(
        self,
        store: RunStore,
        specs_root: Path,
        fire_fn: FireFn,
        *,
        tick_s: float = 30.0,
        time_fn: Callable[[], float] = time.time,
    ):
        self._store = store
        self._specs_root = specs_root
        self._fire_fn = fire_fn
        self._tick_s = tick_s
        self._time_fn = time_fn
        self._stopped = asyncio.Event()
        # Initialize "scheduler started at" so fresh triggers don't fire
        # backlog. Captured at construction so tests can drive deterministic
        # sequences.
        self._started_at = time_fn()

    def stop(self) -> None:
        self._stopped.set()

    async def run_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("scheduler tick failed")
            try:
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=self._tick_s,
                )
            except asyncio.TimeoutError:
                pass  # normal — interval elapsed

    async def tick(self) -> None:
        """One scheduler iteration. Public so tests can drive it directly."""
        now = self._time_fn()
        triggers = list_trigger_specs(self._specs_root)
        for trigger in triggers:
            try:
                expr = parse_cron(trigger.schedule)
            except ValueError as e:
                log.warning(
                    "trigger %r has invalid schedule %r: %s",
                    trigger.name, trigger.schedule, e,
                )
                continue
            state = self._store.get_trigger_state(trigger.name)
            last = state.last_fired_at if state and state.last_fired_at else self._started_at
            try:
                fire_at = next_fire_at(expr, last)
            except ValueError:
                log.warning(
                    "trigger %r has no fire time within window", trigger.name,
                )
                continue
            if now < fire_at:
                continue
            try:
                await self._fire_fn(trigger, now)
            except Exception:
                log.exception(
                    "trigger %r fire_fn failed", trigger.name,
                )
                # Still record so we don't tight-loop on a broken target.
            self._store.record_trigger_fire(trigger.name, now)


# ---------- production fire_fn ----------


def make_default_fire_fn(
    store: RunStore,
    specs_root: Path,
    spawn_fn: Callable,
) -> FireFn:
    """Build the production `fire_fn`. Spawns the trigger's target as a
    normal agent run (target_kind=agent) or workflow run (target_kind=
    workflow), with `triggered_by=trigger.name` for UI surfacing."""

    async def fire(trigger: TriggerSpec, now: float) -> None:
        if trigger.target_kind == "agent":
            agent_spec = find_spec(specs_root, trigger.target)
            if agent_spec is None:
                log.warning(
                    "trigger %r references unknown agent %r — skipping",
                    trigger.name, trigger.target,
                )
                return
            run_module.spawn(
                store=store,
                agent_name=agent_spec.name,
                spec_hash=agent_spec.spec_hash,
                fork=agent_spec.fork,
                prompt=trigger.prompt,
                triggered_by=trigger.name,
                spawn_fn=spawn_fn,
            )
        elif trigger.target_kind == "workflow":
            wf_spec = find_workflow_spec(specs_root, trigger.target)
            if wf_spec is None:
                log.warning(
                    "trigger %r references unknown workflow %r — skipping",
                    trigger.name, trigger.target,
                )
                return
            wr = store.create_workflow_run(
                workflow_name=wf_spec.name,
                spec_hash=wf_spec.spec_hash,
                prompt=trigger.prompt,
                triggered_by=trigger.name,
            )
            # Popen the workflow daemon (same shape as the
            # spawn_workflow route does).
            from ..routes import _build_workflow_daemon_cmd
            cmd = _build_workflow_daemon_cmd(wr.workflow_run_id, store.db_path)
            proc = spawn_fn(cmd, run_module._REPO_ROOT)
            pid = getattr(proc, "pid", None)
            store.update_workflow_status(
                wr.workflow_run_id, "pending", pid=pid,
            )
        else:
            log.warning(
                "trigger %r has unsupported target_kind %r",
                trigger.name, trigger.target_kind,
            )

    return fire
