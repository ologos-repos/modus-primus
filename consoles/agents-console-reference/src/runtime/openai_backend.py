"""OpenAIBackend — POST /v1/chat/completions with stream:true (SSE).

Lines arrive as `data: {...json...}` (or `data: [DONE]` to terminate).
Each delta has `choices[0].delta.content` for the next text token; the
final chunk (sent because stream_options.include_usage is set) carries
the usage block with `prompt_tokens` / `completion_tokens`.

Tools/function-calling are deferred — text-only in Phase 6.

Credential safety: api_key is held privately, never appears in event
payloads, never logged. Error events use a redacted form (status only).
"""
from __future__ import annotations

import json
import os
from typing import Optional

import aiohttp

from ..specs.model import AgentSpec
from .backend import AgentBackend
from .sink import EventSink
from .usage import normalize_usage


_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIBackend(AgentBackend):
    def __init__(self, model: str, api_key: Optional[str] = None) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY not set — required for openai provider"
            )
        self._model = model
        self._api_key = key

    def __repr__(self) -> str:
        # api_key intentionally omitted.
        return f"OpenAIBackend(model={self._model!r})"

    async def run(
        self, spec: AgentSpec, prompt: str, sink: EventSink
    ) -> None:
        sink.emit("status", {"status": "running"})
        body = {
            "model": self._model,
            "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [
                {"role": "system", "content": spec.system_prompt},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        timeout = aiohttp.ClientTimeout(total=spec.timeout_s)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(_API_URL, headers=headers, json=body) as resp:
                    if resp.status >= 400:
                        sink.emit(
                            "error",
                            {"error": f"openai request failed: status={resp.status}"},
                        )
                        raise RuntimeError(f"openai HTTP {resp.status}")
                    async for line in resp.content:
                        if not _consume_sse_line(line, sink):
                            break  # `data: [DONE]` terminator
        except aiohttp.ClientError as e:
            sink.emit("error", {"error": f"openai network error: {type(e).__name__}"})
            raise
        except TimeoutError:
            sink.emit("error", {"error": f"openai timeout after {spec.timeout_s}s"})
            raise


def _consume_sse_line(line: bytes, sink: EventSink) -> bool:
    """Process one SSE line. Returns False on `data: [DONE]` (caller breaks),
    True otherwise (including blanks and non-data lines)."""
    s = line.strip()
    if not s or not s.startswith(b"data:"):
        return True
    payload = s[len(b"data:"):].strip()
    if payload == b"[DONE]":
        return False
    try:
        chunk = json.loads(payload)
    except json.JSONDecodeError:
        return True
    # Token deltas
    choices = chunk.get("choices") or []
    if choices:
        delta = choices[0].get("delta") or {}
        text = delta.get("content")
        if text:
            sink.emit("token", {"text": text})
    # Trailing chunk carries usage when stream_options.include_usage=true
    usage = chunk.get("usage")
    if usage:
        sink.emit("usage", normalize_usage("openai", usage, final=True))
    return True
