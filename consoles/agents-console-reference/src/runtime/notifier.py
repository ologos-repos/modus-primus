"""Cross-service notifier — when an agent run completes, POST an
`agent_completion` event to the chat service so it lands in the parent
chat turn's buffer.

Successor to the in-process InChatNotifier (replaced as part of [ENTERPRISE: tracker ref],
which split agents and chat into separate aiohttp services). The polling
loop is unchanged; only the delivery mechanism flipped from direct buffer
append to HTTP POST against `{chat_url}/turns/{parent_turn_id}/events`.

Notification state is in-memory (a set of run_ids). On agents service
restart the set is empty → already-notified runs may re-notify; that's
harmless because chat-side buffer GC will drop the parent turn quickly,
and the callback then 404s (logged + dropped).

If chat is unreachable when a run terminates, the notification is dropped.
For single-user, single-host deployment that's the same lossiness as the
prior in-memory behavior on chat-process restart.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

from .store import RunStore


logger = logging.getLogger(__name__)


class HttpCallbackNotifier:
    """Polls the agent store for terminal runs that need cross-service broadcast."""

    POLL_INTERVAL = 2.0
    HTTP_TIMEOUT = 5.0

    def __init__(self, *, store: RunStore, chat_url: str):
        self.store = store
        # Strip trailing slash so we can build URLs by string concat.
        self.chat_url = chat_url.rstrip("/")
        self.notified: set[str] = set()
        self._stopping = False
        self._session: Optional[aiohttp.ClientSession] = None

    async def run_loop(self) -> None:
        """Forever loop. Cancel via task.cancel() to exit cleanly."""
        timeout = aiohttp.ClientTimeout(total=self.HTTP_TIMEOUT)
        self._session = aiohttp.ClientSession(timeout=timeout)
        try:
            while not self._stopping:
                try:
                    await self.check_and_notify()
                except Exception:
                    logger.exception("notifier poll failed")
                try:
                    await asyncio.sleep(self.POLL_INTERVAL)
                except asyncio.CancelledError:
                    break
        finally:
            if self._session is not None:
                await self._session.close()

    async def check_and_notify(self) -> int:
        """Single pass: find newly-terminal runs with parent_turn_id and POST
        agent_completion events to the chat service. Returns the count
        actually delivered this pass.
        """
        delivered = 0
        runs = self.store.list_runs(limit=100)
        for run in runs:
            if run.run_id in self.notified:
                continue
            if run.status not in ("done", "error", "cancelled"):
                continue
            if not run.parent_turn_id:
                continue
            payload = {
                "type": "agent_completion",
                "data": {
                    "run_id": run.run_id,
                    "agent_name": run.agent_name,
                    "status": run.status,
                    "error": run.error,
                    "completed_at": run.completed_at,
                    "exit_code": run.exit_code,
                },
            }
            url = f"{self.chat_url}/turns/{run.parent_turn_id}/events"
            try:
                ok = await self._post(url, payload)
                if ok:
                    self.notified.add(run.run_id)
                    delivered += 1
            except Exception:
                logger.exception(
                    "notifier: POST failed for run %s", run.run_id
                )
                # Don't mark notified — try again next pass.
        return delivered

    async def _post(self, url: str, payload: dict) -> bool:
        """POST the payload; return True iff chat acknowledged or 404'd
        (404 means the parent buffer was GC'd — won't recover, mark notified).
        """
        assert self._session is not None
        async with self._session.post(url, json=payload) as resp:
            if resp.status in (200, 202):
                return True
            if resp.status == 404:
                # Parent buffer no longer exists; nothing we can do, drop it.
                logger.info(
                    "notifier: chat returned 404 for %s; marking notified", url
                )
                return True
            body = await resp.text()
            logger.warning(
                "notifier: chat returned %d for %s: %s",
                resp.status, url, body[:200],
            )
            return False

    def stop(self) -> None:
        self._stopping = True
