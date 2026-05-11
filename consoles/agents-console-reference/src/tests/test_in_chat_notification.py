"""Tests for cross-service notification — HttpCallbackNotifier picks up
terminal runs with parent_turn_id and POSTs an agent_completion event to
the chat service.

Mocks the `_post` method to keep these tests focused on polling/state
behavior. The HTTP transport itself is exercised in integration tests.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import pytest

from means.agents.runtime.notifier import HttpCallbackNotifier
from means.agents.runtime.store import RunStore


# ---------- fixtures ----------


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "agents.sqlite")


class _RecordingNotifier(HttpCallbackNotifier):
    """Records POSTs in-memory instead of hitting HTTP."""

    def __init__(self, *, store: RunStore, chat_url: str = "http://chat.test"):
        super().__init__(store=store, chat_url=chat_url)
        self.calls: list[tuple[str, dict]] = []
        self.next_response: bool = True  # what _post returns
        self.next_exception: Optional[Exception] = None

    async def _post(self, url: str, payload: dict) -> bool:
        if self.next_exception is not None:
            exc = self.next_exception
            self.next_exception = None
            raise exc
        self.calls.append((url, payload))
        return self.next_response


@pytest.fixture
def notifier(store: RunStore) -> _RecordingNotifier:
    return _RecordingNotifier(store=store)


# ---------- check_and_notify behavior ----------


async def test_skips_running_runs(store, notifier):
    run = store.create_run(
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
        parent_turn_id="turn-1",
    )
    store.update_status(run.run_id, "running")

    count = await notifier.check_and_notify()
    assert count == 0
    assert notifier.calls == []


async def test_skips_runs_without_parent_turn(store, notifier):
    run = store.create_run(
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
    )
    store.update_status(run.run_id, "done", exit_code=0)

    count = await notifier.check_and_notify()
    assert count == 0
    assert notifier.calls == []


async def test_posts_completion_to_chat(store, notifier):
    run = store.create_run(
        agent_name="hello-world", spec_hash="h", fork="dev", prompt="p",
        parent_turn_id="turn-1", parent_session_id="sess-1",
    )
    store.update_status(run.run_id, "done", exit_code=0)

    count = await notifier.check_and_notify()
    assert count == 1
    assert len(notifier.calls) == 1
    url, payload = notifier.calls[0]
    assert url == "http://chat.test/turns/turn-1/events"
    assert payload["type"] == "agent_completion"
    assert payload["data"]["run_id"] == run.run_id
    assert payload["data"]["agent_name"] == "hello-world"
    assert payload["data"]["status"] == "done"
    assert payload["data"]["exit_code"] == 0


async def test_posts_for_error_status(store, notifier):
    run = store.create_run(
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
        parent_turn_id="turn-1",
    )
    store.update_status(run.run_id, "error", error="boom", exit_code=1)

    count = await notifier.check_and_notify()
    assert count == 1
    payload = notifier.calls[0][1]
    assert payload["data"]["status"] == "error"
    assert payload["data"]["error"] == "boom"


async def test_posts_for_cancelled_status(store, notifier):
    run = store.create_run(
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
        parent_turn_id="turn-1",
    )
    store.update_status(run.run_id, "cancelled", exit_code=-1)

    count = await notifier.check_and_notify()
    assert count == 1


async def test_idempotent_on_repeated_passes(store, notifier):
    """Same terminal run should be POSTed exactly once across multiple passes."""
    run = store.create_run(
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
        parent_turn_id="turn-1",
    )
    store.update_status(run.run_id, "done", exit_code=0)

    c1 = await notifier.check_and_notify()
    c2 = await notifier.check_and_notify()
    c3 = await notifier.check_and_notify()
    assert c1 == 1
    assert c2 == 0
    assert c3 == 0
    assert len(notifier.calls) == 1


async def test_marks_notified_on_404(store, notifier):
    """Chat returns 404 (parent buffer GC'd) → mark notified, don't retry.

    The recording fake's _post just returns next_response, so we simulate
    the 404-mapped-to-True behavior the real _post implements.
    """
    run = store.create_run(
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
        parent_turn_id="ghost-turn",
    )
    store.update_status(run.run_id, "done", exit_code=0)

    # next_response=True simulates _post returning True (whether from 200,
    # 202, or 404 — all three mean "stop retrying").
    notifier.next_response = True
    await notifier.check_and_notify()
    assert run.run_id in notifier.notified
    c = await notifier.check_and_notify()
    assert c == 0


async def test_preserves_unnotified_on_post_failure(store, notifier):
    """If _post returns False (5xx etc), run is NOT marked notified — retry next pass."""
    run = store.create_run(
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
        parent_turn_id="turn-1",
    )
    store.update_status(run.run_id, "done", exit_code=0)
    notifier.next_response = False

    count = await notifier.check_and_notify()
    assert count == 0  # post failed → not counted, not marked
    assert run.run_id not in notifier.notified

    # Recover — flip response, retry succeeds
    notifier.next_response = True
    count2 = await notifier.check_and_notify()
    assert count2 == 1
    assert run.run_id in notifier.notified


async def test_preserves_unnotified_on_post_exception(store, notifier):
    """A raised exception from _post (network down) → swallow + don't mark notified."""
    run = store.create_run(
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
        parent_turn_id="turn-1",
    )
    store.update_status(run.run_id, "done", exit_code=0)
    notifier.next_exception = RuntimeError("connection refused")

    count = await notifier.check_and_notify()
    assert count == 0
    assert run.run_id not in notifier.notified


async def test_handles_multiple_runs_one_pass(store, notifier):
    a = store.create_run(
        agent_name="x", spec_hash="h", fork="dev", prompt="p1",
        parent_turn_id="turn-1",
    )
    store.update_status(a.run_id, "done", exit_code=0)
    b = store.create_run(
        agent_name="y", spec_hash="h", fork="dev", prompt="p2",
        parent_turn_id="turn-2",
    )
    store.update_status(b.run_id, "error", error="boom", exit_code=1)

    count = await notifier.check_and_notify()
    assert count == 2
    assert len(notifier.calls) == 2
    urls = {c[0] for c in notifier.calls}
    assert "http://chat.test/turns/turn-1/events" in urls
    assert "http://chat.test/turns/turn-2/events" in urls


async def test_chat_url_trailing_slash_stripped(store):
    notifier = _RecordingNotifier(store=store, chat_url="http://chat.test/")
    assert notifier.chat_url == "http://chat.test"


# ---------- run_loop ----------


async def test_run_loop_stops_cleanly(store, notifier):
    """task.cancel() → run_loop exits within ~POLL_INTERVAL."""
    notifier.POLL_INTERVAL = 0.05
    task = asyncio.create_task(notifier.run_loop())
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert task.cancelled() or task.done()


async def test_run_loop_continues_after_exception(store, notifier):
    """A synchronous exception in check_and_notify shouldn't kill the loop."""
    notifier.POLL_INTERVAL = 0.02
    calls = []

    async def boom():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("transient")
        notifier.stop()

    notifier.check_and_notify = boom  # type: ignore[assignment]
    await notifier.run_loop()
    assert len(calls) >= 3


# ---------- stop() ----------


def test_stop_sets_flag(notifier):
    assert notifier._stopping is False
    notifier.stop()
    assert notifier._stopping is True
