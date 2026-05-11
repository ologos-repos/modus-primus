"""Tests for runtime/services.query_status + query_logs.

Mocks `asyncio.create_subprocess_exec` to feed canned output. No real
systemctl/journalctl invocation — the unit tests verify shape and
defense-in-depth around graceful failure.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from means.agents.runtime.services import query_logs, query_status


class _FakeProc:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def _patch_exec(proc: _FakeProc, captured: list | None = None):
    """Patch create_subprocess_exec; optionally capture call args."""
    async def fake_exec(*args, **kwargs):
        if captured is not None:
            captured.append((args, kwargs))
        return proc
    return patch(
        "means.agents.runtime.services.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=fake_exec),
    )


# ---------- query_status ----------


@pytest.mark.asyncio
async def test_query_status_parses_active_service():
    """Canonical Ubuntu systemctl-show output for an active service."""
    out = (
        b"ActiveState=active\n"
        b"SubState=running\n"
        b"MainPID=12345\n"
        b"MemoryCurrent=67108864\n"
        b"ExecMainStartTimestamp=Thu 2026-05-07 10:00:00 CDT\n"
        b"Result=success\n"
    )
    with _patch_exec(_FakeProc(stdout=out)):
        result = await query_status("foo.service")
    assert result["active_state"] == "active"
    assert result["sub_state"] == "running"
    assert result["main_pid"] == 12345
    assert result["memory_bytes"] == 67108864
    assert result["started_at"] == "Thu 2026-05-07 10:00:00 CDT"
    assert result["result"] == "success"


@pytest.mark.asyncio
async def test_query_status_main_pid_zero_normalizes_to_none():
    """A oneshot/timer with no main process reports MainPID=0 — clean to None."""
    out = b"ActiveState=active\nSubState=waiting\nMainPID=0\n"
    with _patch_exec(_FakeProc(stdout=out)):
        result = await query_status("foo.timer")
    assert result["main_pid"] is None
    assert result["sub_state"] == "waiting"


@pytest.mark.asyncio
async def test_query_status_memory_not_set():
    """MemoryCurrent=[not set] when accounting is disabled."""
    out = b"ActiveState=active\nMemoryCurrent=[not set]\n"
    with _patch_exec(_FakeProc(stdout=out)):
        result = await query_status("foo.service")
    assert result["memory_bytes"] is None


@pytest.mark.asyncio
async def test_query_status_failed_unit_returns_defaults():
    """systemctl returns rc=4 for unknown units → graceful defaults."""
    with _patch_exec(_FakeProc(stdout=b"", returncode=4)):
        result = await query_status("ghost.service")
    assert result["active_state"] == "unknown"
    assert result["main_pid"] is None
    assert result["started_at"] is None


@pytest.mark.asyncio
async def test_query_status_passes_user_flag_for_user_scope():
    captured: list = []
    with _patch_exec(_FakeProc(stdout=b"ActiveState=active\n"), captured):
        await query_status("foo.service", scope="user")
    args, kwargs = captured[0]
    assert args[0] == "systemctl"
    assert "--user" in args
    assert "show" in args


@pytest.mark.asyncio
async def test_query_status_omits_user_flag_for_system_scope():
    captured: list = []
    with _patch_exec(_FakeProc(stdout=b"ActiveState=active\n"), captured):
        await query_status("foo.service", scope="system")
    args, kwargs = captured[0]
    assert "--user" not in args


@pytest.mark.asyncio
async def test_query_status_handles_missing_systemctl():
    """FileNotFoundError (systemctl not installed) → graceful defaults."""
    async def boom(*_args, **_kwargs):
        raise FileNotFoundError("systemctl")
    with patch(
        "means.agents.runtime.services.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=boom),
    ):
        result = await query_status("foo.service")
    assert result["active_state"] == "unknown"


@pytest.mark.asyncio
async def test_query_status_unknown_keys_ignored():
    """Permissive parser — extra keys don't break the dict shape."""
    out = b"ActiveState=active\nNewFutureKey=42\n"
    with _patch_exec(_FakeProc(stdout=out)):
        result = await query_status("foo.service")
    assert result["active_state"] == "active"
    assert "NewFutureKey" not in result  # unknown keys aren't surfaced


# ---------- query_logs ----------


@pytest.mark.asyncio
async def test_query_logs_returns_lines_oldest_first():
    out = (
        b"2026-05-07T17:01:00-0500 host svc[123]: started\n"
        b"2026-05-07T17:02:00-0500 host svc[123]: tick\n"
        b"2026-05-07T17:03:00-0500 host svc[123]: tock\n"
    )
    with _patch_exec(_FakeProc(stdout=out)):
        lines = await query_logs("foo.service", n=10)
    assert len(lines) == 3
    assert "started" in lines[0]
    assert "tock" in lines[2]


@pytest.mark.asyncio
async def test_query_logs_strips_trailing_cr():
    out = b"line one\r\nline two\r\n"
    with _patch_exec(_FakeProc(stdout=out)):
        lines = await query_logs("foo.service")
    assert lines == ["line one", "line two"]


@pytest.mark.asyncio
async def test_query_logs_empty_on_failure():
    """Journal access denied or unit unknown → empty list, no raise."""
    with _patch_exec(_FakeProc(stdout=b"", returncode=1)):
        lines = await query_logs("ghost.service")
    assert lines == []


@pytest.mark.asyncio
async def test_query_logs_passes_n_and_no_pager():
    captured: list = []
    with _patch_exec(_FakeProc(stdout=b""), captured):
        await query_logs("foo.service", n=42)
    args, _ = captured[0]
    assert args[0] == "journalctl"
    assert "--user" in args
    assert "-u" in args and "foo.service" in args
    assert "-n" in args and "42" in args
    assert "--no-pager" in args


@pytest.mark.asyncio
async def test_query_logs_systemd_colors_disabled_in_env():
    """SYSTEMD_COLORS=0 prevents ANSI escapes in journal output."""
    captured: list = []
    with _patch_exec(_FakeProc(stdout=b""), captured):
        await query_logs("foo.service")
    _, kwargs = captured[0]
    assert kwargs["env"]["SYSTEMD_COLORS"] == "0"
