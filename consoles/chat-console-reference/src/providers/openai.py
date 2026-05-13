"""OpenAI-compatible chat provider — streams from any `/v1/chat/completions`
endpoint that implements the OpenAI wire format. Works with api.openai.com,
LM Studio, vLLM, llama.cpp server, etc.

Wire format: SSE. Each line is `data: {...json...}` or `data: [DONE]`. Each
delta carries `choices[0].delta.content` for the next text token. Some
"reasoning" models (e.g. gemma-4-26b-a4b) also emit `delta.reasoning_content`
chunks BEFORE the visible content — those are the model's internal
thinking and are filtered out of the chat surface so operators only see
the final reply.

Session continuity is maintained per-process in an in-memory dict keyed
by session_id. For durable continuity, the SQLite-backed history at
app[HISTORY_KEY] is the canonical record; a future revision may preload
session messages from history on resume.

Configuration via env vars:
    OPENAI_BASE_URL    — base URL up to `/v1` (default api.openai.com/v1)
    OPENAI_API_KEY     — auth header (LM-Studio-style servers accept any
                         non-empty value, e.g. "lm-studio")
    OPENAI_MODEL       — model id served by that endpoint
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

import aiohttp

from turns import TurnBuffer, TurnEvent

from .base import Provider

logger = logging.getLogger(__name__)


# Per-process session history.
# session_id -> list of {"role": "user"|"assistant"|"system", "content": str}
_SESSION_HISTORY: dict[str, list[dict[str, str]]] = {}
_SESSION_LOCK = asyncio.Lock()


_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(Provider):
    """Stream a turn from an OpenAI-compatible /v1/chat/completions endpoint
    into the TurnBuffer.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: float = 600.0,
        persona_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ):
        self.base_url = (
            base_url or os.environ.get("OPENAI_BASE_URL", _DEFAULT_BASE_URL)
        ).rstrip("/")
        # Tolerate operators who paste a base without /v1.
        if not self.base_url.endswith("/v1") and "/v" not in self.base_url[-6:]:
            self.base_url = f"{self.base_url}/v1"
        self.model = model or os.environ.get("OPENAI_MODEL", "")
        if not self.model:
            raise RuntimeError(
                "OPENAI_MODEL not set — required for openai provider"
            )
        # LM-Studio-style servers accept any non-empty key. Don't error on
        # missing key — let the server reject it if it actually requires one.
        self.api_key = (
            api_key or os.environ.get("OPENAI_API_KEY") or "lm-studio"
        )
        self.timeout_seconds = timeout_seconds
        self.persona_name = (
            persona_name
            or os.environ.get("CHAT_CONSOLE_PERSONA_NAME", "chat console")
        )
        env_prompt = os.environ.get("CHAT_CONSOLE_SYSTEM_PROMPT", "").strip()
        self.system_prompt = (
            system_prompt or env_prompt or self._default_system_prompt()
        )

    def _default_system_prompt(self) -> str:
        return (
            f"You are {self.persona_name} — the chat console of a Modus "
            f"Primus enclave. You run on the {self.model} model. When asked "
            f"who or what you are, identify as \"{self.persona_name}\" and "
            f"acknowledge the underlying model ({self.model}); do not pretend "
            f"to be a different assistant.\n\n"
            "You CANNOT spawn, dispatch, invoke, run, or execute agents "
            "yourself. Agent dispatch is handled upstream by the intent "
            "router; if this turn reached you it means the router decided "
            "the operator's request did not need an agent. Therefore:\n\n"
            "  - NEVER fabricate an execution log, run id, status sequence, "
            "or fake agent name like 'SOL_SCANNER_01'.\n"
            "  - NEVER claim 'agent X deployed', 'spawning…', 'dispatched', "
            "or similar.\n"
            "  - If the operator clearly asked for a dispatch, answer the "
            "underlying question directly AND say one sentence acknowledging "
            "that you didn't actually spawn anything — name the available "
            "catalog agents if helpful (the intent router knows the "
            "catalog; you do not).\n\n"
            "Be concise. Avoid filler unless the operator asks for depth."
        )

    async def __call__(
        self,
        buf: TurnBuffer,
        prompt: str,
        *,
        session_id: str,
        is_new_session: bool,
    ) -> None:
        await buf.start()
        try:
            async with _SESSION_LOCK:
                if is_new_session or session_id not in _SESSION_HISTORY:
                    _SESSION_HISTORY[session_id] = (
                        [{"role": "system", "content": self.system_prompt}]
                        if self.system_prompt else []
                    )
                history = list(_SESSION_HISTORY[session_id])
            messages = history + [{"role": "user", "content": prompt}]

            payload = {
                "model": self.model,
                "messages": messages,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            url = f"{self.base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            }

            assistant_chunks: list[str] = []
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status >= 300:
                        body = await resp.text()
                        raise RuntimeError(
                            f"openai endpoint returned HTTP {resp.status}: "
                            f"{body[:500]}"
                        )
                    async for raw_line in resp.content:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        payload_str = line[len("data:"):].strip()
                        if payload_str == "[DONE]":
                            break
                        try:
                            obj = json.loads(payload_str)
                        except json.JSONDecodeError:
                            logger.warning(
                                "openai: malformed SSE line: %r", line[:200]
                            )
                            continue
                        choices = obj.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta") or {}
                            # Skip reasoning_content — internal thinking,
                            # not for the operator chat surface.
                            text = delta.get("content")
                            if text:
                                assistant_chunks.append(text)
                                await buf.append(
                                    TurnEvent(type="token", data={"text": text})
                                )

            full_reply = "".join(assistant_chunks)
            async with _SESSION_LOCK:
                _SESSION_HISTORY[session_id] = messages + [
                    {"role": "assistant", "content": full_reply}
                ]
            await buf.finish()
        except Exception as e:
            logger.exception("openai provider error")
            await buf.finish(error=str(e))
