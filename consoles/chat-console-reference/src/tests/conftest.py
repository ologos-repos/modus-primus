"""Pytest configuration. Adds console/ to sys.path so `from providers import …` works.

Autouse fixture isolates CHAT_CONSOLE_HISTORY into a per-test tmp path so any
build_app() call that doesn't explicitly override the env var still
lands in tmp instead of polluting the live ./data/history.sqlite. This
is a defense-in-depth backstop for the issue caught by the rendered
turn-walk on 2026-05-08 (test pollution into prod).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _isolate_workspace_history(tmp_path, monkeypatch):
    """Force every test's chat history into tmp. Tests that need a specific
    path (e.g., to seed disk artifacts) can override CHAT_CONSOLE_HISTORY explicitly."""
    monkeypatch.setenv("CHAT_CONSOLE_HISTORY", str(tmp_path / "_autouse_history.sqlite"))
