"""systemctl/journalctl wrappers for surfacing service status.

The fleet UI calls these on every panel render — multiplied across ~14
units, that's 14 forks per refresh. Each call is well under 50ms so
parallelizing via `asyncio.gather` keeps the total under 100ms; if it
ever becomes a problem the natural next step is a 2-second TTL cache.

Both helpers return graceful defaults on subprocess failure (missing
unit, missing systemctl, journal access denied) — a fresh checkout
hasn't installed every unit yet, and that's not an error from the
console's perspective.

`SYSTEMD_COLORS=0` is set in the env so journal output never carries
ANSI escape sequences that would break JSON serialization downstream.
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional


_STATUS_PROPERTIES = (
    "ActiveState", "SubState", "MainPID", "MemoryCurrent",
    "ExecMainStartTimestamp", "Result",
)
_STATUS_DEFAULTS: dict[str, Optional[object]] = {
    "active_state": "unknown",
    "sub_state": None,
    "main_pid": None,
    "memory_bytes": None,
    "started_at": None,        # raw timestamp string (unparsed)
    "result": None,
}


async def query_status(unit: str, scope: str = "user") -> dict:
    """Return a normalized status dict for `unit` via `systemctl show`.
    On any failure returns _STATUS_DEFAULTS so the caller still has a
    well-shaped response."""
    args = _systemctl_args(scope) + [
        "show", unit, f"--property={','.join(_STATUS_PROPERTIES)}",
    ]
    rc, stdout, _ = await _run("systemctl", args)
    if rc != 0:
        return dict(_STATUS_DEFAULTS)
    return _parse_status(stdout)


async def query_logs(unit: str, scope: str = "user", n: int = 30) -> list[str]:
    """Return the last `n` journal lines for `unit`, oldest-first. Empty
    list on failure (journal access denied, missing unit, etc.)."""
    args = _journalctl_args(scope) + [
        "-u", unit, "-n", str(n), "--no-pager", "--output=short-iso",
    ]
    rc, stdout, _ = await _run("journalctl", args)
    if rc != 0:
        return []
    # journalctl with -n N outputs (up to) N lines; preserve order, strip CR
    return [line.rstrip("\r") for line in stdout.splitlines() if line]


def _systemctl_args(scope: str) -> list[str]:
    return ["--user"] if scope == "user" else []


def _journalctl_args(scope: str) -> list[str]:
    return ["--user"] if scope == "user" else []


def _parse_status(stdout: str) -> dict:
    """Parse `systemctl show` KEY=VALUE output into our normalized shape.
    Permissive: split on first `=`, ignore unknown keys, treat absent
    fields as defaults."""
    fields: dict[str, str] = {}
    for line in stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key] = value
    # MemoryCurrent of `[not set]` (when memory accounting disabled) and
    # MainPID of `0` (no main process) are normalized to None.
    main_pid_raw = fields.get("MainPID", "0")
    memory_raw = fields.get("MemoryCurrent", "")
    return {
        "active_state": fields.get("ActiveState") or "unknown",
        "sub_state": fields.get("SubState") or None,
        "main_pid": int(main_pid_raw) if main_pid_raw.isdigit() and int(main_pid_raw) > 0 else None,
        "memory_bytes": int(memory_raw) if memory_raw.isdigit() else None,
        "started_at": fields.get("ExecMainStartTimestamp") or None,
        "result": fields.get("Result") or None,
    }


async def _run(cmd: str, args: list[str]) -> tuple[int, str, str]:
    """Run `cmd` with `args`, capturing stdout/stderr. Returns (rc, out, err).
    On any unexpected exception (FileNotFoundError, etc.) returns
    (-1, '', repr(exc)) so callers don't have to handle it specially."""
    env = dict(os.environ)
    env["SYSTEMD_COLORS"] = "0"
    try:
        proc = await asyncio.create_subprocess_exec(
            cmd, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        out_b, err_b = await proc.communicate()
        return (
            proc.returncode if proc.returncode is not None else -1,
            out_b.decode("utf-8", errors="replace"),
            err_b.decode("utf-8", errors="replace"),
        )
    except (FileNotFoundError, PermissionError) as e:
        return -1, "", repr(e)
