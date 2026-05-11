"""EventSink — backends call this to record events.

The sink owns persistence (RunStore.append_event). In-chat notification
happens elsewhere (notifier.py, after the run completes), so the sink stays
small and synchronous.
"""
from __future__ import annotations

from .store import RunStore


class EventSink:
    """Thin wrapper that bundles `run_id` so backends don't have to thread
    it through every emit call."""

    def __init__(self, store: RunStore, run_id: str):
        self.store = store
        self.run_id = run_id

    def emit(self, event_type: str, data: dict) -> int:
        """Append an event; returns assigned seq."""
        return self.store.append_event(self.run_id, event_type, data)
