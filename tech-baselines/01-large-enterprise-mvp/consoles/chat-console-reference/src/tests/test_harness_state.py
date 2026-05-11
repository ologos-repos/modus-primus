"""Tests for harness.state — wraps `means/scripts/session-start.py --json`.

Subprocess is mocked so CI doesn't need a real session-start.py to run; the
fixture creates a fake script on disk so resolution succeeds.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import harness
from harness import HarnessUnavailable, fetch_harness_state, reset_cache


SAMPLE_STATE = {
    "timestamp": "2026-05-07T13:00:00+00:00",
    "git": {
        "branch": "main",
        "head": "deadbeef",
        "clean": True,
        "uncommitted": [],
        "ahead": 0,
        "behind": 0,
    },
    "services": [
        {"unit": "[ENTERPRISE: personal chat bridge service].service", "active": True},
        {"unit": "comment-monitor.timer", "next": "Thu 2026-05-07 18:00:00 CDT"},
    ],
    "commits": ["deadbeef console: chunk 5 harness module"],
    "meta_context": [
        {"file": "claude-code.md", "modified": "2026-05-07 13:00 UTC", "age_hours": 0}
    ],
    "cross_ai": [
        {"number": 11, "title": "Session-protocol contract", "updated": "2026-05-07T12:00:00Z"}
    ],
}


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_cache()
    yield
    reset_cache()


@pytest.fixture
def workspace_root(tmp_path: Path, monkeypatch) -> Path:
    """Lay down a fake means/scripts/session-start.py so resolution succeeds.
    Subprocess invocation is mocked separately, so script contents don't matter."""
    scripts = tmp_path / "means" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "session-start.py").write_text("# stub\n")
    monkeypatch.setenv("CHAT_CONSOLE_WORKSPACE", str(tmp_path))
    return tmp_path


class _FakeProc:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def _patch_subprocess(stdout: bytes, stderr: bytes = b"", returncode: int = 0):
    fake = _FakeProc(stdout, stderr, returncode)
    return patch(
        "harness.state.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    )


# ---- happy path ----


async def test_fetch_returns_parsed_json(workspace_root):
    payload = json.dumps(SAMPLE_STATE).encode()
    with _patch_subprocess(payload):
        data = await fetch_harness_state()
    assert data["git"]["branch"] == "main"
    assert data["services"][0]["unit"] == "[ENTERPRISE: personal chat bridge service].service"


async def test_fetch_caches_within_ttl(workspace_root):
    payload = json.dumps(SAMPLE_STATE).encode()
    with patch(
        "harness.state.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_FakeProc(payload)),
    ) as mock_exec:
        await fetch_harness_state(ttl_seconds=60.0)
        await fetch_harness_state(ttl_seconds=60.0)
        await fetch_harness_state(ttl_seconds=60.0)
    # 3 calls but only 1 subprocess invocation
    assert mock_exec.call_count == 1


async def test_fetch_force_bypasses_cache(workspace_root):
    payload = json.dumps(SAMPLE_STATE).encode()
    with patch(
        "harness.state.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_FakeProc(payload)),
    ) as mock_exec:
        await fetch_harness_state(ttl_seconds=60.0)
        await fetch_harness_state(ttl_seconds=60.0, force=True)
    assert mock_exec.call_count == 2


async def test_fetch_refreshes_after_ttl_expiry(workspace_root):
    payload = json.dumps(SAMPLE_STATE).encode()
    with patch(
        "harness.state.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_FakeProc(payload)),
    ) as mock_exec:
        await fetch_harness_state(ttl_seconds=0.0)
        # ttl=0 means every call is fresh
        await fetch_harness_state(ttl_seconds=0.0)
    assert mock_exec.call_count == 2


async def test_fetch_workspace_root_override(tmp_path):
    scripts = tmp_path / "means" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "session-start.py").write_text("# stub\n")
    payload = json.dumps(SAMPLE_STATE).encode()
    with _patch_subprocess(payload):
        data = await fetch_harness_state(workspace_root=str(tmp_path))
    assert data["git"]["branch"] == "main"


# ---- error paths ----


async def test_no_workspace_root_raises(monkeypatch):
    monkeypatch.delenv("CHAT_CONSOLE_WORKSPACE", raising=False)
    with pytest.raises(HarnessUnavailable, match="not set"):
        await fetch_harness_state()


async def test_workspace_root_missing_dir_raises(monkeypatch):
    monkeypatch.setenv("CHAT_CONSOLE_WORKSPACE", "/nonexistent/path/here")
    with pytest.raises(HarnessUnavailable, match="does not exist"):
        await fetch_harness_state()


async def test_script_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_CONSOLE_WORKSPACE", str(tmp_path))
    # No means/scripts/session-start.py written
    with pytest.raises(HarnessUnavailable, match="not found"):
        await fetch_harness_state()


async def test_script_nonzero_exit_raises(workspace_root):
    with _patch_subprocess(b"", stderr=b"oops\n", returncode=1):
        with pytest.raises(HarnessUnavailable, match="exited 1"):
            await fetch_harness_state()


async def test_script_malformed_json_raises(workspace_root):
    with _patch_subprocess(b"not json"):
        with pytest.raises(HarnessUnavailable, match="parse"):
            await fetch_harness_state()


async def test_failed_fetch_does_not_poison_cache(workspace_root):
    """An error must not leave bad data in the cache."""
    with _patch_subprocess(b"not json"):
        with pytest.raises(HarnessUnavailable):
            await fetch_harness_state()
    # Subsequent successful call should populate cleanly
    payload = json.dumps(SAMPLE_STATE).encode()
    with _patch_subprocess(payload):
        data = await fetch_harness_state()
    assert data["git"]["branch"] == "main"
