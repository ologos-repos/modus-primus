"""IntentRoutingProvider — wraps a base provider and routes "spawn-agent"
intent to agents-console while leaving conversational turns untouched.

Flow per turn:

  1. Fetch agents-console catalog (cached briefly).
  2. Run IntentClassifier against the operator prompt.
  3. If action == "chat": delegate to the wrapped base provider.
  4. If action == "spawn_agent":
       a. POST agents-console /agents/{name}/run with the synthesized
          agent_prompt.
       b. Poll /runs/{run_id} until the run reaches a terminal status
          (done | error | cancelled | denied).
       c. Emit a status header + the agent's final reply (or error) as
          token events on the TurnBuffer.

Streaming the run output live (SSE /runs/{run_id}/stream) is deferred to
v0.1 — v0 emits the completed reply as a single block. Approval-gated
agents return status="awaiting_approval"; v0 surfaces that and instructs
the operator to approve via agents-console (no inline approval UI yet).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import aiohttp

from intent_router import (
    AgentCatalogEntry,
    IntentClassifier,
    IntentDecision,
)
from turns import TurnBuffer, TurnEvent

from .base import Provider

logger = logging.getLogger(__name__)


_TERMINAL_STATUSES = {"done", "error", "cancelled", "denied"}


class IntentRoutingProvider(Provider):
    """Routing wrapper around a base text-generation Provider."""

    def __init__(
        self,
        base: Provider,
        agents_console_url: Optional[str] = None,
        classifier: Optional[IntentClassifier] = None,
        poll_interval_seconds: float = 1.5,
        run_timeout_seconds: float = 300.0,
        catalog_ttl_seconds: float = 30.0,
    ):
        self.base = base
        self.agents_console_url = (
            agents_console_url
            or os.environ.get("AGENTS_CONSOLE_INTERNAL_URL")
            or os.environ.get("AGENTS_CONSOLE_URL")
            or "http://localhost:8205"
        ).rstrip("/")
        self.classifier = classifier or IntentClassifier()
        self.poll_interval_seconds = poll_interval_seconds
        self.run_timeout_seconds = run_timeout_seconds
        self.catalog_ttl_seconds = catalog_ttl_seconds
        self._catalog: list[AgentCatalogEntry] = []
        self._catalog_fetched_at: float = 0.0

    async def __call__(
        self,
        buf: TurnBuffer,
        prompt: str,
        *,
        session_id: str,
        is_new_session: bool,
    ) -> None:
        catalog = await self._get_catalog()
        decision = await self.classifier.classify(prompt, catalog)

        if decision.action != "spawn_agent" or not decision.agent:
            # Pure chat — delegate. Base provider is responsible for the
            # entire buf lifecycle (start/append/finish).
            await self.base(
                buf,
                prompt,
                session_id=session_id,
                is_new_session=is_new_session,
            )
            return

        # Dispatch path. From here we own the buf lifecycle.
        await buf.start()
        try:
            await self._emit_text(
                buf,
                f"_Dispatching `{decision.agent}` via agents-console…_\n",
            )
            await self._dispatch_and_wait(
                buf,
                agent=decision.agent,
                agent_prompt=decision.agent_prompt or prompt,
                session_id=session_id,
            )
            await buf.finish()
        except Exception as e:
            logger.exception("intent-routing dispatch failed")
            await self._emit_text(buf, f"\n_(error: {e})_")
            await buf.finish(error=str(e))

    # -------- helpers --------

    async def _get_catalog(self) -> list[AgentCatalogEntry]:
        now = time.time()
        if self._catalog and (now - self._catalog_fetched_at) < self.catalog_ttl_seconds:
            return self._catalog
        url = f"{self.agents_console_url}/agents"
        try:
            timeout = aiohttp.ClientTimeout(total=10.0)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(url) as resp:
                    if resp.status >= 300:
                        logger.warning(
                            "agents-console catalog HTTP %d", resp.status
                        )
                        return self._catalog  # last-good
                    data = await resp.json()
        except Exception as e:
            logger.warning("catalog fetch failed: %r", e)
            return self._catalog  # last-good

        entries: list[AgentCatalogEntry] = []
        for raw in data:
            if not isinstance(raw, dict):
                continue
            entries.append(
                AgentCatalogEntry(
                    name=raw.get("name") or "",
                    domain=raw.get("domain") or "",
                    fork=raw.get("fork") or "",
                    description=raw.get("description") or "",
                )
            )
        self._catalog = [e for e in entries if e.name]
        self._catalog_fetched_at = now
        return self._catalog

    async def _dispatch_and_wait(
        self,
        buf: TurnBuffer,
        *,
        agent: str,
        agent_prompt: str,
        session_id: str,
    ) -> None:
        spawn_url = f"{self.agents_console_url}/agents/{agent}/run"
        timeout = aiohttp.ClientTimeout(total=self.run_timeout_seconds)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                spawn_url,
                json={"prompt": agent_prompt, "session_id": session_id},
            ) as resp:
                if resp.status >= 300:
                    body = await resp.text()
                    raise RuntimeError(
                        f"agents-console returned HTTP {resp.status}: {body[:300]}"
                    )
                spawn_body = await resp.json()
            run_id = spawn_body.get("run_id") or spawn_body.get("id")
            initial_status = spawn_body.get("status") or "pending"
            if not run_id:
                raise RuntimeError(
                    f"agents-console spawn response missing run_id: {spawn_body!r}"
                )

            await self._emit_text(
                buf,
                f"_run_id `{run_id}` (status: {initial_status})_\n\n",
            )

            if initial_status == "awaiting_approval":
                await self._emit_text(
                    buf,
                    "**This agent requires operator approval.** "
                    f"Approve at the [Agents Console]"
                    f"(/agents-console#run-{run_id}) — the run will not "
                    "start until you do.",
                )
                return

            # Poll until terminal.
            deadline = time.time() + self.run_timeout_seconds
            poll_url = f"{self.agents_console_url}/runs/{run_id}"
            last_status: Optional[str] = None
            while True:
                if time.time() > deadline:
                    raise RuntimeError(
                        f"run {run_id} did not terminate within "
                        f"{self.run_timeout_seconds:.0f}s"
                    )
                try:
                    async with session.get(poll_url) as r:
                        if r.status >= 300:
                            await asyncio.sleep(self.poll_interval_seconds)
                            continue
                        run = await r.json()
                except aiohttp.ClientError:
                    await asyncio.sleep(self.poll_interval_seconds)
                    continue

                status = (run.get("status") or "").lower()
                if status != last_status and status:
                    await self._emit_text(buf, f"_status: {status}…_\n")
                    last_status = status
                if status in _TERMINAL_STATUSES:
                    reply = (
                        run.get("final_reply")
                        or run.get("reply")
                        or run.get("output")
                        or run.get("summary")
                        or ""
                    )
                    error = run.get("error") or ""
                    if status == "done":
                        await self._emit_text(buf, "\n" + (reply or "_(no output)_"))
                    elif status == "error":
                        await self._emit_text(
                            buf, f"\n**Run failed:** {error or 'unknown error'}"
                        )
                    elif status == "cancelled":
                        await self._emit_text(buf, "\n_Run cancelled._")
                    elif status == "denied":
                        await self._emit_text(
                            buf, f"\n_Run denied:_ {error or 'no reason given'}"
                        )
                    return
                await asyncio.sleep(self.poll_interval_seconds)

    async def _emit_text(self, buf: TurnBuffer, text: str) -> None:
        if not text:
            return
        await buf.append(TurnEvent(type="token", data={"text": text}))
