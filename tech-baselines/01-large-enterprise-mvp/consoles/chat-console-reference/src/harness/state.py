"""Live chat-console state — wraps `means/scripts/session-start.py --json`.

The script is the canonical session-start contract (cross-AI #3) so the
console reflects the same data terminal sessions see, without duplicating
the logic. Result is cached in-process for TTL seconds; clients can force
a refresh by passing `force=True`.

If CHAT_CONSOLE_WORKSPACE is unset or the script is missing, the harness module raises
HarnessUnavailable — the console then runs as a plain chat app, no sidebar.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional


class HarnessUnavailable(Exception):
    """CHAT_CONSOLE_WORKSPACE not set, script missing, or script failed."""


_DEFAULT_TTL = 30.0

# Module-level cache (single-instance console). Test code resets via reset_cache().
_CACHE: dict = {"data": None, "fetched_at": 0.0}


def reset_cache() -> None:
    _CACHE["data"] = None
    _CACHE["fetched_at"] = 0.0


def _resolve_workspace_root(override: Optional[str]) -> Path:
    root = override or os.environ.get("CHAT_CONSOLE_WORKSPACE")
    if not root:
        raise HarnessUnavailable("CHAT_CONSOLE_WORKSPACE not set")
    p = Path(root).expanduser()
    if not p.is_dir():
        raise HarnessUnavailable(f"CHAT_CONSOLE_WORKSPACE does not exist: {root}")
    return p


def _resolve_script(workspace_root: Path) -> Path:
    script = workspace_root / "means" / "scripts" / "session-start.py"
    if not script.exists():
        raise HarnessUnavailable(f"session-start.py not found at {script}")
    return script


async def fetch_harness_state(
    *,
    workspace_root: Optional[str] = None,
    force: bool = False,
    ttl_seconds: float = _DEFAULT_TTL,
) -> dict:
    """Return parsed session-start JSON. Cached unless `force=True` or stale."""
    now = time.time()
    if (
        not force
        and _CACHE["data"] is not None
        and (now - _CACHE["fetched_at"]) < ttl_seconds
    ):
        return _CACHE["data"]

    root = _resolve_workspace_root(workspace_root)
    script = _resolve_script(root)

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script),
        "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(root),
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    if proc.returncode != 0:
        err = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
        raise HarnessUnavailable(
            f"session-start.py exited {proc.returncode}: {err or '(no stderr)'}"
        )
    try:
        data = json.loads(stdout_bytes.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise HarnessUnavailable(f"could not parse session-start JSON: {e}")

    _CACHE["data"] = data
    _CACHE["fetched_at"] = now
    return data
