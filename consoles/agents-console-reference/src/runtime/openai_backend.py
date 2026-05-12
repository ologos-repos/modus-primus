"""OpenAIBackend — POST <base>/chat/completions with stream:true (SSE).

Lines arrive as `data: {...json...}` (or `data: [DONE]` to terminate).
Each delta has `choices[0].delta.content` for the next text token; the
final chunk (sent because stream_options.include_usage is set) carries
the usage block with `prompt_tokens` / `completion_tokens`.

Base URL is configurable via OPENAI_BASE_URL — defaults to
`https://api.openai.com/v1`. Any OpenAI-compatible /v1 endpoint works:
LM Studio (`http://host:1237/v1`), vLLM, llama.cpp server, etc. The
backend appends `/chat/completions` to whatever base it receives, so
operators just point at the `/v1` root of their service. API keys
required by the upstream service are read from OPENAI_API_KEY;
LM-Studio-style servers accept any non-empty value.

Tools/function-calling are deferred — text-only.

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


_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIBackend(AgentBackend):
    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY not set — required for openai provider "
                "(LM-Studio-style servers accept any non-empty value)"
            )
        self._model = model
        self._api_key = key
        self._base_url = (
            base_url
            or os.environ.get("OPENAI_BASE_URL")
            or _DEFAULT_BASE_URL
        ).rstrip("/")
        # Tolerate operators who paste a base without /v1.
        if not self._base_url.endswith("/v1"):
            # Heuristic: leave alone if it already includes a versioned path,
            # else append /v1.
            if "/v" not in self._base_url[-6:]:
                self._base_url = f"{self._base_url}/v1"
        self._url = f"{self._base_url}/chat/completions"

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
                async with session.post(self._url, headers=headers, json=body) as resp:
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
