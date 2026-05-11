"""GeminiBackend — POST :streamGenerateContent?alt=sse with system + user.

Lines arrive as `data: {...json...}` (no `[DONE]` terminator — the stream
just ends). Each event has `candidates[0].content.parts[N].text`; multiple
parts can appear in one event and must concatenate in order. Some events
also carry `usageMetadata`; the latest seen wins, emitted as a final
`usage` event after the stream closes.

Tools/function-calling are deferred — text-only in Phase 6.

Credential safety: api_key lives in the URL query string per Google's API.
The URL is NEVER logged or emitted; error events use status-only redacted
form (Gemini error bodies can echo the request key, so the body is also
never surfaced).
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


_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiBackend(AgentBackend):
    def __init__(self, model: str, api_key: Optional[str] = None) -> None:
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY not set — required for gemini provider"
            )
        self._model = model
        self._api_key = key

    def __repr__(self) -> str:
        return f"GeminiBackend(model={self._model!r})"

    async def run(
        self, spec: AgentSpec, prompt: str, sink: EventSink
    ) -> None:
        sink.emit("status", {"status": "running"})
        body = {
            "systemInstruction": {"parts": [{"text": spec.system_prompt}]},
            "contents": [
                {"role": "user", "parts": [{"text": prompt}]},
            ],
        }
        url = (
            f"{_API_BASE}/{self._model}:streamGenerateContent"
            f"?alt=sse&key={self._api_key}"
        )
        timeout = aiohttp.ClientTimeout(total=spec.timeout_s)
        latest_usage: Optional[dict] = None
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body) as resp:
                    if resp.status >= 400:
                        # Status only — never URL or body (key echoes).
                        sink.emit(
                            "error",
                            {"error": f"gemini request failed: status={resp.status}"},
                        )
                        raise RuntimeError(f"gemini HTTP {resp.status}")
                    async for line in resp.content:
                        usage_block = _consume_sse_line(line, sink)
                        if usage_block is not None:
                            latest_usage = usage_block
        except aiohttp.ClientError as e:
            sink.emit("error", {"error": f"gemini network error: {type(e).__name__}"})
            raise
        except TimeoutError:
            sink.emit("error", {"error": f"gemini timeout after {spec.timeout_s}s"})
            raise
        if latest_usage is not None:
            sink.emit("usage", normalize_usage("gemini", latest_usage, final=True))


def _consume_sse_line(line: bytes, sink: EventSink) -> Optional[dict]:
    """Parse one SSE line. Emits `token` for each text part. Returns the
    `usageMetadata` dict if present so the caller can track the latest."""
    s = line.strip()
    if not s or not s.startswith(b"data:"):
        return None
    payload = s[len(b"data:"):].strip()
    try:
        chunk = json.loads(payload)
    except json.JSONDecodeError:
        return None
    candidates = chunk.get("candidates") or []
    if candidates:
        parts = candidates[0].get("content", {}).get("parts") or []
        for part in parts:
            text = part.get("text")
            if text:
                sink.emit("token", {"text": text})
    return chunk.get("usageMetadata")
