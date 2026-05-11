"""Per-turn output buffer + registry. Server-authoritative streaming.

A turn is one user input + the model's response (token stream + tool calls).
Generation runs to completion server-side regardless of client connection;
multiple subscribers can connect, each resumable from any event offset.

Phase 1: memory-resident with write-through to disk (durability + crash
recovery for free). Disk-spillover-on-pressure is deferred until empirically
needed; the stream_from() interface is offset-based so spillover can be
added without changing callers.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import AsyncIterator, Optional


class TurnStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class TurnEvent:
    """One event in a turn's stream. `type` ∈ {token, tool_call, tool_result, status, error}."""
    type: str
    data: dict = field(default_factory=dict)

    def to_jsonl(self) -> str:
        return json.dumps({"type": self.type, "data": self.data}, separators=(",", ":"))

    @classmethod
    def from_jsonl(cls, line: str) -> "TurnEvent":
        obj = json.loads(line)
        return cls(type=obj["type"], data=obj.get("data", {}))


def new_turn_id() -> str:
    """Sortable turn id: <epoch_ms>-<short_uuid>."""
    return f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"


class TurnBuffer:
    """File-backed event buffer for one turn. Single writer, many async readers.

    Writers call start(), append() repeatedly, then finish(). Readers call
    stream_from(offset) and asynchronously iterate raw JSONL lines until the
    turn ends. Readers connecting after the turn finishes still get the
    full replay.
    """

    def __init__(
        self,
        turn_id: str,
        data_dir: Path,
        session_id: Optional[str] = None,
    ):
        self.turn_id = turn_id
        self.data_dir = data_dir
        self.session_id = session_id
        self.path = data_dir / f"{turn_id}.jsonl"
        self.status = TurnStatus.PENDING
        self.error: Optional[str] = None
        self._events: list[str] = []
        self._cond = asyncio.Condition()

    @property
    def event_count(self) -> int:
        return len(self._events)

    async def start(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text("")
        # Sidecar metadata — preserves session_id alongside the JSONL so
        # disk-only artifacts (when the in-memory registry has expired) can
        # still be backfilled into the durable history sqlite. Per chat-console#27.
        meta_path = self.data_dir / f"{self.turn_id}.meta.json"
        meta_path.write_text(
            json.dumps({
                "turn_id": self.turn_id,
                "session_id": self.session_id,
                "started_at": time.time(),
            })
        )
        async with self._cond:
            self.status = TurnStatus.RUNNING
            self._cond.notify_all()

    async def append(self, event: TurnEvent) -> None:
        line = event.to_jsonl()
        with self.path.open("a") as f:
            f.write(line + "\n")
        async with self._cond:
            self._events.append(line)
            self._cond.notify_all()

    async def finish(self, error: Optional[str] = None) -> None:
        async with self._cond:
            if error is not None:
                self.error = error
                self.status = TurnStatus.ERROR
            else:
                self.status = TurnStatus.DONE
            self._cond.notify_all()

    async def stream_from(self, from_index: int = 0) -> AsyncIterator[str]:
        """Yield raw JSONL lines starting at event index `from_index`.

        Replays past events from memory, then tails new appends until the
        turn reaches a terminal status. Snapshots under the condition lock
        so no events are missed and none are duplicated.
        """
        seen = max(from_index, 0)
        while True:
            async with self._cond:
                while len(self._events) <= seen and self.status == TurnStatus.RUNNING:
                    await self._cond.wait()
                pending = self._events[seen:]
                end_status = self.status
            for line in pending:
                yield line
            seen += len(pending)
            if end_status != TurnStatus.RUNNING:
                return


class TurnRegistry:
    """Process-local turn id → buffer registry. GC's old finished turns."""

    def __init__(self, data_dir: Path, retention_seconds: float = 3600.0):
        self.data_dir = data_dir
        self.retention_seconds = retention_seconds
        self._turns: dict[str, TurnBuffer] = {}
        self._created_at: dict[str, float] = {}

    def create(self, session_id: Optional[str] = None) -> TurnBuffer:
        turn_id = new_turn_id()
        buf = TurnBuffer(
            turn_id=turn_id, data_dir=self.data_dir, session_id=session_id
        )
        self._turns[turn_id] = buf
        self._created_at[turn_id] = time.time()
        return buf

    def get(self, turn_id: str) -> Optional[TurnBuffer]:
        return self._turns.get(turn_id)

    def gc(self, now: Optional[float] = None) -> int:
        """Drop finished turns older than retention. Returns count dropped."""
        now = now if now is not None else time.time()
        dropped = 0
        for tid in list(self._created_at.keys()):
            buf = self._turns.get(tid)
            if buf is None:
                self._created_at.pop(tid, None)
                continue
            if buf.status in (TurnStatus.DONE, TurnStatus.ERROR):
                if now - self._created_at[tid] > self.retention_seconds:
                    self._turns.pop(tid, None)
                    self._created_at.pop(tid, None)
                    dropped += 1
        return dropped
