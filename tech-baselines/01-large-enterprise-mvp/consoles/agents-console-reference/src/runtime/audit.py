"""Append-only audit log for security-relevant agent events.

Design: one process-wide jsonl at `data/audit.jsonl`. Each record is a
single line of JSON with `ts`, `event`, plus arbitrary kwargs. No
rotation in Phase 4 (sortable timestamps + manual prune later);
operational state is in SQLite — this log is purely the security record.

Records the runtime emits today:
  run_spawned        — a run was created (status pending or awaiting_approval)
  approval_requested — an awaiting_approval run is now visible to approvers
  approval_decision  — approve/deny outcome with approver + reason
  run_completed      — terminal status; includes qa_outcome when present

Future phases extend the event vocabulary; readers must tolerate unknown
keys (forward-compat).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional


_DEFAULT_AUDIT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "audit.jsonl"
)


class AuditLog:
    """Thread-safe-by-OS append; no in-process locking. SQLite is the
    canonical store for run state; this is the immutable record."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else _DEFAULT_AUDIT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: str, **fields: Any) -> dict:
        """Append a single audit record. Returns the dict that was written."""
        rec: dict[str, Any] = {"ts": time.time(), "event": event}
        rec.update(fields)
        line = json.dumps(rec, separators=(",", ":"), default=str)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        return rec

    def read_all(self) -> list[dict]:
        """Read the full log (cheap for Phase 4 expected volumes)."""
        if not self.path.exists():
            return []
        records: list[dict] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records
