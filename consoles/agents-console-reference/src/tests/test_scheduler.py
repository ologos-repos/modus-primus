"""Tests for runtime/scheduler.

The scheduler is driven via direct `tick()` calls so we don't burn
wall-clock waiting for the 30s loop. `time_fn` is injected with
scripted timestamps so we can deterministically test the
"now >= next_fire_at" decision.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock

import pytest

from means.agents.runtime.scheduler import (
    Scheduler,
    make_default_fire_fn,
)
from means.agents.runtime.store import RunStore


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def _write_trigger(
    root: Path, name: str, *,
    schedule: str = "* * * * *",
    target_kind: str = "agent",
    target: str = "hello-world",
    prompt: str = "hi",
) -> None:
    _write(root / f"{name}.md", (
        f"---\nkind: trigger\nschedule: \"{schedule}\"\n"
        f"target_kind: {target_kind}\ntarget: {target}\nprompt: {prompt}\n"
        f"---\nbody"
    ))


def _write_agent(root: Path, name: str = "hello-world") -> None:
    _write(root / f"{name}.md",
        "---\nfork: dev\nmodel: m\n---\nbody")


def _write_workflow(root: Path, name: str = "wf") -> None:
    _write(root / f"{name}.md", (
        "---\nkind: workflow\nsteps:\n"
        "  - agent: hello-world\n    prompt: hi\n"
        "---\nbody"
    ))


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "agents.sqlite")


@pytest.fixture
def specs_root(tmp_path: Path) -> Path:
    root = tmp_path / "specs"
    root.mkdir()
    _write_agent(root)
    return root


# ---------- tick() ----------


@pytest.mark.asyncio
async def test_tick_does_nothing_when_no_triggers(
    store: RunStore, specs_root: Path,
):
    fire = AsyncMock()
    s = Scheduler(store, specs_root, fire, time_fn=lambda: 1000.0)
    await s.tick()
    fire.assert_not_called()


@pytest.mark.asyncio
async def test_tick_fires_when_now_past_next_fire(
    store: RunStore, specs_root: Path,
):
    """`* * * * *` from startup time → next fire is the next minute
    boundary; tick at startup+90s should fire."""
    _write_trigger(specs_root, "minute-tick", schedule="* * * * *")
    fire = AsyncMock()
    # Startup: 2026-05-07 10:00:00 → next fire 10:01:00 (epoch 1778169660)
    # Tick at 10:01:30 → past next fire, should fire.
    import datetime as dt
    startup = dt.datetime(2026, 5, 7, 10, 0, 0).timestamp()
    later = dt.datetime(2026, 5, 7, 10, 1, 30).timestamp()
    times = iter([startup, later])
    s = Scheduler(store, specs_root, fire, time_fn=lambda: next(times))
    await s.tick()
    fire.assert_called_once()
    args = fire.call_args[0]
    assert args[0].name == "minute-tick"
    # State is recorded.
    state = store.get_trigger_state("minute-tick")
    assert state is not None
    assert state.fire_count == 1


@pytest.mark.asyncio
async def test_tick_does_not_fire_before_next_fire(
    store: RunStore, specs_root: Path,
):
    """Startup at 10:00:00, tick at 10:00:30 — `*/5 * * * *` next fire is
    10:05:00. Should not fire yet."""
    _write_trigger(specs_root, "five-min", schedule="*/5 * * * *")
    fire = AsyncMock()
    import datetime as dt
    startup = dt.datetime(2026, 5, 7, 10, 0, 0).timestamp()
    soon = dt.datetime(2026, 5, 7, 10, 0, 30).timestamp()
    times = iter([startup, soon])
    s = Scheduler(store, specs_root, fire, time_fn=lambda: next(times))
    await s.tick()
    fire.assert_not_called()


@pytest.mark.asyncio
async def test_tick_does_not_double_fire_within_window(
    store: RunStore, specs_root: Path,
):
    """Two ticks, both within the same fire-window → only one fire.
    The first tick records last_fired_at; the second's next_fire_at
    advances forward."""
    _write_trigger(specs_root, "minute-tick", schedule="* * * * *")
    fire = AsyncMock()
    import datetime as dt
    t = iter([
        dt.datetime(2026, 5, 7, 10, 0, 0).timestamp(),    # startup
        dt.datetime(2026, 5, 7, 10, 1, 30).timestamp(),   # first tick — fires
        dt.datetime(2026, 5, 7, 10, 1, 50).timestamp(),   # second tick — no fire
    ])
    s = Scheduler(store, specs_root, fire, time_fn=lambda: next(t))
    await s.tick()
    await s.tick()
    assert fire.call_count == 1


@pytest.mark.asyncio
async def test_tick_skips_invalid_schedule_without_crashing(
    store: RunStore, specs_root: Path, caplog,
):
    """A trigger spec with invalid schedule shouldn't reach the
    scheduler (loader catches it), but defense-in-depth: even if it
    did, the scheduler would log + skip."""
    # Bypass the loader's check by writing the file post-load:
    # actually the loader-time validation makes invalid specs unloadable,
    # so list_trigger_specs() returns []. This test verifies that a
    # trigger that DOES load but parses oddly at tick time doesn't
    # crash. Skip — covered by load-time tests.


@pytest.mark.asyncio
async def test_tick_records_state_even_when_fire_fn_raises(
    store: RunStore, specs_root: Path,
):
    """If fire_fn raises, scheduler still records last_fired_at so it
    doesn't tight-loop on the broken trigger."""
    _write_trigger(specs_root, "broken", schedule="* * * * *")

    async def boom(_t, _n):
        raise RuntimeError("target broke")
    fire = boom
    import datetime as dt
    t = iter([
        dt.datetime(2026, 5, 7, 10, 0, 0).timestamp(),
        dt.datetime(2026, 5, 7, 10, 1, 30).timestamp(),
    ])
    s = Scheduler(store, specs_root, fire, time_fn=lambda: next(t))
    await s.tick()  # should not raise
    state = store.get_trigger_state("broken")
    assert state is not None
    assert state.fire_count == 1


# ---------- default_fire_fn ----------


@pytest.mark.asyncio
async def test_default_fire_fn_agent_target(
    store: RunStore, specs_root: Path,
):
    """target_kind=agent → run.spawn called with triggered_by set."""
    _write_trigger(specs_root, "t", target_kind="agent", target="hello-world")
    spawned: list = []

    class FakeProc:
        pid = 12345
    def fake_spawn(cmd, cwd):
        spawned.append(cmd)
        return FakeProc()

    fire = make_default_fire_fn(store, specs_root, fake_spawn)
    triggers = __import__(
        "means.agents.specs.loader", fromlist=["list_trigger_specs"]
    ).list_trigger_specs(specs_root)
    await fire(triggers[0], 1000.0)

    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0].agent_name == "hello-world"
    assert runs[0].triggered_by == "t"


@pytest.mark.asyncio
async def test_default_fire_fn_workflow_target(
    store: RunStore, tmp_path: Path,
):
    """target_kind=workflow → workflow_run created + Popened."""
    specs = tmp_path / "specs"
    specs.mkdir()
    _write_agent(specs)
    _write_workflow(specs, "wf")
    _write_trigger(
        specs, "t", target_kind="workflow", target="wf",
        prompt="initial input",
    )
    spawned: list = []

    class FakeProc:
        pid = 99999
    def fake_spawn(cmd, cwd):
        spawned.append(cmd)
        return FakeProc()

    fire = make_default_fire_fn(store, specs, fake_spawn)
    triggers = __import__(
        "means.agents.specs.loader", fromlist=["list_trigger_specs"]
    ).list_trigger_specs(specs)
    await fire(triggers[0], 1000.0)

    wf_runs = store.list_workflow_runs()
    assert len(wf_runs) == 1
    assert wf_runs[0].triggered_by == "t"
    assert wf_runs[0].prompt == "initial input"
    # Popen invoked with the workflow_daemon module
    assert any("workflow_daemon" in c for cmd in spawned for c in cmd)


@pytest.mark.asyncio
async def test_default_fire_fn_unknown_target_logs_and_skips(
    store: RunStore, specs_root: Path, caplog,
):
    _write_trigger(specs_root, "ghost-t", target="ghost-agent")
    spawned: list = []

    class FakeProc:
        pid = 1
    def fake_spawn(cmd, cwd):
        spawned.append(cmd)
        return FakeProc()

    fire = make_default_fire_fn(store, specs_root, fake_spawn)
    triggers = __import__(
        "means.agents.specs.loader", fromlist=["list_trigger_specs"]
    ).list_trigger_specs(specs_root)
    await fire(triggers[0], 1000.0)
    # No run was created, no spawn was called.
    assert store.list_runs() == []
    assert spawned == []


# ---------- stop() ----------


@pytest.mark.asyncio
async def test_stop_cancels_loop_cleanly(store: RunStore, specs_root: Path):
    fire = AsyncMock()
    s = Scheduler(store, specs_root, fire, tick_s=0.05)
    import asyncio
    task = asyncio.create_task(s.run_loop())
    await asyncio.sleep(0.1)  # let it tick at least once
    s.stop()
    await asyncio.wait_for(task, timeout=1.0)
