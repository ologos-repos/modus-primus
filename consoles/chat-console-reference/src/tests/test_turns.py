"""Tests for the turn buffer + registry. These underwrite tab-suspension resilience.

Coverage: append + replay, offset replay, exact-once delivery across reconnect,
concurrent reader+writer, multiple subscribers at different offsets, late readers
after finish, status transitions, error path, disk persistence, registry GC.
"""
import asyncio
import json
from pathlib import Path

import pytest

from turns import TurnBuffer, TurnEvent, TurnRegistry, TurnStatus, new_turn_id


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "turns"


async def _collect(buf: TurnBuffer, from_index: int = 0) -> list[str]:
    return [line async for line in buf.stream_from(from_index)]


async def test_new_turn_id_unique():
    a, b = new_turn_id(), new_turn_id()
    assert a != b
    # Sortable: both start with epoch-ms prefix
    assert a.split("-")[0].isdigit()


async def test_event_jsonl_round_trip():
    ev = TurnEvent(type="token", data={"text": "hello"})
    decoded = TurnEvent.from_jsonl(ev.to_jsonl())
    assert decoded.type == "token"
    assert decoded.data == {"text": "hello"}


async def test_append_and_full_replay(data_dir: Path):
    buf = TurnBuffer(turn_id="t1", data_dir=data_dir)
    await buf.start()
    await buf.append(TurnEvent(type="token", data={"text": "a"}))
    await buf.append(TurnEvent(type="token", data={"text": "b"}))
    await buf.finish()

    parsed = [json.loads(line)["data"]["text"] for line in await _collect(buf)]
    assert parsed == ["a", "b"]


async def test_replay_from_offset(data_dir: Path):
    buf = TurnBuffer(turn_id="t2", data_dir=data_dir)
    await buf.start()
    for i in range(5):
        await buf.append(TurnEvent(type="token", data={"text": str(i)}))
    await buf.finish()

    parsed = [json.loads(line)["data"]["text"] for line in await _collect(buf, from_index=3)]
    assert parsed == ["3", "4"]


async def test_offset_beyond_count_returns_empty_after_finish(data_dir: Path):
    buf = TurnBuffer(turn_id="t2b", data_dir=data_dir)
    await buf.start()
    await buf.append(TurnEvent(type="token", data={"text": "x"}))
    await buf.finish()
    assert await _collect(buf, from_index=99) == []


async def test_concurrent_reader_writer(data_dir: Path):
    """Reader connects mid-flight, sees subsequent events live."""
    buf = TurnBuffer(turn_id="t3", data_dir=data_dir)
    await buf.start()
    await buf.append(TurnEvent(type="token", data={"text": "a"}))

    received: list[str] = []

    async def reader():
        async for line in buf.stream_from(0):
            received.append(json.loads(line)["data"]["text"])

    reader_task = asyncio.create_task(reader())
    await asyncio.sleep(0.01)
    await buf.append(TurnEvent(type="token", data={"text": "b"}))
    await buf.append(TurnEvent(type="token", data={"text": "c"}))
    await buf.finish()
    await reader_task

    assert received == ["a", "b", "c"]


async def test_two_readers_at_different_offsets(data_dir: Path):
    buf = TurnBuffer(turn_id="t4", data_dir=data_dir)
    await buf.start()
    for i in range(3):
        await buf.append(TurnEvent(type="token", data={"text": str(i)}))

    r1: list[str] = []
    r2: list[str] = []

    async def reader(out: list[str], offset: int):
        async for line in buf.stream_from(offset):
            out.append(json.loads(line)["data"]["text"])

    t1 = asyncio.create_task(reader(r1, 0))
    t2 = asyncio.create_task(reader(r2, 2))
    await asyncio.sleep(0.01)
    await buf.append(TurnEvent(type="token", data={"text": "3"}))
    await buf.finish()
    await asyncio.gather(t1, t2)

    assert r1 == ["0", "1", "2", "3"]
    assert r2 == ["2", "3"]


async def test_late_reader_after_finish(data_dir: Path):
    """Reader connecting after turn finished gets the full replay."""
    buf = TurnBuffer(turn_id="t5", data_dir=data_dir)
    await buf.start()
    for i in range(3):
        await buf.append(TurnEvent(type="token", data={"text": str(i)}))
    await buf.finish()

    parsed = [json.loads(line)["data"]["text"] for line in await _collect(buf)]
    assert parsed == ["0", "1", "2"]


async def test_exact_once_after_simulated_disconnect(data_dir: Path):
    """Reader resumes from offset N → no duplicates, no gaps."""
    buf = TurnBuffer(turn_id="t6", data_dir=data_dir)
    await buf.start()
    for i in range(10):
        await buf.append(TurnEvent(type="token", data={"text": str(i)}))
    await buf.finish()

    first_chunk = []
    async for line in buf.stream_from(0):
        first_chunk.append(json.loads(line)["data"]["text"])
        if len(first_chunk) == 5:
            break  # simulate iOS-tab-suspension drop

    second_chunk = [
        json.loads(line)["data"]["text"]
        for line in await _collect(buf, from_index=5)
    ]
    combined = first_chunk + second_chunk
    assert combined == [str(i) for i in range(10)]
    assert len(set(combined)) == 10  # no duplicates


async def test_status_transitions(data_dir: Path):
    buf = TurnBuffer(turn_id="t7", data_dir=data_dir)
    assert buf.status == TurnStatus.PENDING
    await buf.start()
    assert buf.status == TurnStatus.RUNNING
    await buf.finish()
    assert buf.status == TurnStatus.DONE


async def test_error_status(data_dir: Path):
    buf = TurnBuffer(turn_id="t8", data_dir=data_dir)
    await buf.start()
    await buf.finish(error="boom")
    assert buf.status == TurnStatus.ERROR
    assert buf.error == "boom"


async def test_disk_persistence(data_dir: Path):
    buf = TurnBuffer(turn_id="t9", data_dir=data_dir)
    await buf.start()
    await buf.append(TurnEvent(type="token", data={"text": "persisted"}))
    await buf.finish()

    file_lines = buf.path.read_text().strip().split("\n")
    assert len(file_lines) == 1
    assert json.loads(file_lines[0])["data"]["text"] == "persisted"


async def test_registry_create_and_get(data_dir: Path):
    reg = TurnRegistry(data_dir=data_dir)
    buf = reg.create()
    assert reg.get(buf.turn_id) is buf
    assert reg.get("nonexistent") is None


async def test_registry_gc_removes_old_finished_turns(data_dir: Path):
    reg = TurnRegistry(data_dir=data_dir, retention_seconds=0.0)
    buf = reg.create()
    await buf.start()
    await buf.finish()
    # retention_seconds=0 + tiny sleep → finished turn is past retention
    await asyncio.sleep(0.001)
    dropped = reg.gc()
    assert dropped == 1
    assert reg.get(buf.turn_id) is None


async def test_registry_gc_keeps_running_turns(data_dir: Path):
    reg = TurnRegistry(data_dir=data_dir, retention_seconds=0.0)
    buf = reg.create()
    await buf.start()
    # Don't finish — must not be GC'd
    dropped = reg.gc()
    assert dropped == 0
    assert reg.get(buf.turn_id) is buf
