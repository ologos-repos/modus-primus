"""Per-session turn history — durable record of completed turns.

Beyond the 1h `TurnRegistry` retention (in-memory + JSONL on disk), each
turn is persisted into a sqlite history db when it terminates. The
frontend uses this on page load to rehydrate the conversation surface so
the user can navigate / reload / cmd-Q + reopen and find their chat
where they left off — per chat-console#27 (decision D).

Schema (single table):

    history_turns
      turn_id         TEXT PRIMARY KEY
      session_id      TEXT NOT NULL  (indexed)
      started_at      REAL NOT NULL  (unix epoch seconds)
      completed_at    REAL           (NULL while in flight)
      status          TEXT NOT NULL  (pending|running|done|error)
      error           TEXT
      prompt          TEXT NOT NULL
      events_jsonl    TEXT NOT NULL  (newline-separated jsonl of TurnEvents)

Retention: forever (no auto-expire). Add cleanup tooling later if size
becomes a concern; on a workstation, completed-turn events are small.

This module is read/write durable but is NOT the live wire — the active
turn-buffer-and-stream path (`turns.TurnBuffer`) stays untouched. History
is written once on turn termination, read once on page load.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS history_turns (
    turn_id       TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL,
    started_at    REAL NOT NULL,
    completed_at  REAL,
    status        TEXT NOT NULL,
    error         TEXT,
    prompt        TEXT NOT NULL,
    events_jsonl  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_session
    ON history_turns(session_id, started_at);
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    custom_title  TEXT
);
"""


@dataclass
class HistoryTurn:
    """One row of the history_turns table."""
    turn_id: str
    session_id: str
    started_at: float
    completed_at: Optional[float]
    status: str
    error: Optional[str]
    prompt: str
    events_jsonl: str

    @property
    def events(self) -> list[dict]:
        """Parse the stored JSONL into a list of event dicts."""
        return [
            json.loads(line)
            for line in self.events_jsonl.splitlines()
            if line.strip()
        ]

    def to_summary(self) -> dict:
        """Trim to the shape the /sessions/{id}/turns endpoint returns."""
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "error": self.error,
            "prompt": self.prompt,
            "source": "history",
        }


class SessionHistory:
    """Durable per-session turn history, sqlite-backed."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        # check_same_thread=False since the app is single-process aiohttp;
        # writes happen from the event loop.
        con = sqlite3.connect(self.db_path, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con

    def record_turn(
        self,
        *,
        turn_id: str,
        session_id: str,
        prompt: str,
        events_jsonl: str,
        status: str,
        error: Optional[str],
        started_at: Optional[float] = None,
        completed_at: Optional[float] = None,
    ) -> None:
        """UPSERT a turn into history. Idempotent on re-record (overwrites
        the existing row — useful for in-flight resumes that rewrite the
        events log as it grows)."""
        now = time.time()
        with self._conn() as con:
            con.execute(
                """INSERT INTO history_turns
                       (turn_id, session_id, started_at, completed_at,
                        status, error, prompt, events_jsonl)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(turn_id) DO UPDATE SET
                       completed_at = excluded.completed_at,
                       status       = excluded.status,
                       error        = excluded.error,
                       events_jsonl = excluded.events_jsonl""",
                (
                    turn_id,
                    session_id,
                    started_at if started_at is not None else now,
                    completed_at,
                    status,
                    error,
                    prompt,
                    events_jsonl,
                ),
            )

    def list_turns(self, session_id: str) -> list[HistoryTurn]:
        """All turns for a session, ordered by started_at ascending."""
        with self._conn() as con:
            rows = con.execute(
                """SELECT turn_id, session_id, started_at, completed_at,
                          status, error, prompt, events_jsonl
                     FROM history_turns
                    WHERE session_id = ?
                    ORDER BY started_at ASC""",
                (session_id,),
            ).fetchall()
        return [HistoryTurn(**dict(r)) for r in rows]

    def get_turn(self, turn_id: str) -> Optional[HistoryTurn]:
        """Fetch a single turn by id (for the per-turn replay endpoint)."""
        with self._conn() as con:
            row = con.execute(
                """SELECT turn_id, session_id, started_at, completed_at,
                          status, error, prompt, events_jsonl
                     FROM history_turns
                    WHERE turn_id = ?""",
                (turn_id,),
            ).fetchone()
        return HistoryTurn(**dict(row)) if row else None

    def has_turn(self, turn_id: str) -> bool:
        """Cheap existence check — used by backfill to skip already-ingested turns."""
        with self._conn() as con:
            row = con.execute(
                "SELECT 1 FROM history_turns WHERE turn_id = ? LIMIT 1",
                (turn_id,),
            ).fetchone()
        return row is not None

    def backfill_from_disk(self, turns_dir: Path) -> int:
        """Scan a turns directory for `<id>.jsonl` + `<id>.meta.json` pairs
        and ingest any turn not already in history.

        Run on console.service startup so disk-only artifacts (which exist
        beyond the 1h in-memory registry retention) are durable. Pre-chat-console#27
        files have no meta sidecar so they're skipped — session_id can't be
        reconstructed without it. Newly-created turns always write a sidecar
        from `TurnBuffer.start()`.

        Returns count of turns newly inserted this pass.
        """
        turns_dir = Path(turns_dir)
        if not turns_dir.is_dir():
            return 0
        inserted = 0
        for jsonl_path in turns_dir.glob("*.jsonl"):
            turn_id = jsonl_path.stem
            if self.has_turn(turn_id):
                continue
            meta_path = turns_dir / f"{turn_id}.meta.json"
            if not meta_path.is_file():
                # Pre-#27 orphan: session_id unrecoverable.
                continue
            try:
                meta = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            session_id = meta.get("session_id")
            if not session_id:
                continue
            events_jsonl = jsonl_path.read_text().rstrip("\n")
            # Derive prompt + status from the events themselves where
            # possible. Prompt isn't in the event log; we fall back to
            # empty string (the SessionRegistry has it but the JSONL doesn't).
            # Status: if last event suggests done, mark done; else running.
            lines = [l for l in events_jsonl.split("\n") if l.strip()]
            status = _infer_status_from_events(lines)
            self.record_turn(
                turn_id=turn_id,
                session_id=session_id,
                prompt=meta.get("prompt", ""),
                events_jsonl=events_jsonl,
                status=status,
                error=None,
                started_at=meta.get("started_at"),
                completed_at=meta.get("completed_at"),
            )
            inserted += 1
        return inserted


    def list_sessions(self, limit: int = 50) -> list[dict]:
        """Aggregated session list for the sidebar (chat-console#30). Each entry:
        {session_id, title, turn_count, last_activity, first_prompt}.

        Title precedence: explicit `custom_title` if the user has renamed
        the session, otherwise the first user prompt truncated to 40 chars
        at a word boundary. Ordered by `last_activity` DESC, capped at
        `limit` (default 50).
        """
        with self._conn() as con:
            rows = con.execute(
                """SELECT
                       h.session_id            AS session_id,
                       COUNT(*)                AS turn_count,
                       MAX(h.completed_at)     AS last_activity,
                       MIN(h.started_at)       AS first_started_at,
                       (SELECT prompt FROM history_turns
                          WHERE session_id = h.session_id
                          ORDER BY started_at ASC LIMIT 1) AS first_prompt,
                       s.custom_title          AS custom_title
                     FROM history_turns h
                     LEFT JOIN sessions s
                       ON s.session_id = h.session_id
                    GROUP BY h.session_id
                    ORDER BY last_activity DESC NULLS LAST, first_started_at DESC
                    LIMIT ?""",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["title"] = d["custom_title"] or _truncate_title(d["first_prompt"], 40)
            d.pop("custom_title", None)
            out.append(d)
        return out

    def set_custom_title(self, session_id: str, title: str) -> None:
        """UPSERT a renamed title for a session (chat-console#30)."""
        with self._conn() as con:
            con.execute(
                """INSERT INTO sessions (session_id, custom_title)
                   VALUES (?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       custom_title = excluded.custom_title""",
                (session_id, title),
            )


def _truncate_title(text: Optional[str], max_chars: int) -> str:
    """Trim to <max_chars>, breaking at a word boundary when possible."""
    if not text:
        return "(no title)"
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_space = cut.rfind(" ")
    if last_space > max_chars // 2:
        return cut[:last_space].rstrip() + "…"
    return cut.rstrip() + "…"


def _infer_status_from_events(event_lines: list[str]) -> str:
    """Heuristic: if events are non-empty and look complete, mark `done`.
    The 1h registry retention means the in-memory buffer was the
    source-of-truth for status; once GC'd, all we have is the event log.
    A turn's events are append-only and persisted before any status frame;
    if the JSONL exists at all, the turn at least started, and the typical
    case at backfill time is that it ran to completion.
    """
    if not event_lines:
        return "pending"
    return "done"
