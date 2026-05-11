"""OllamaBackend — POST /api/chat with stream:true, NDJSON response.

Ollama's chat endpoint streams newline-delimited JSON (NOT SSE). Each line
is a complete JSON object; non-empty `message.content` becomes a `token`
event; the line with `done: true` carries the usage counters. Errors emit
an `error` event before raising so the daemon writes a clean run row.

Tools/function-calling are deferred to a later phase — this backend is
text-only. The judge stays claude-CLI based regardless of which provider
ran the agent.
"""
from __future__ import annotations

import json
from typing import Any

import aiohttp

from ..specs.model import AgentSpec
from .backend import AgentBackend
from .sink import EventSink
from .usage import normalize_usage


class OllamaBackend(AgentBackend):
    def __init__(
        self, hosts: dict[str, str], host_alias: str, model_tag: str
    ) -> None:
        if host_alias not in hosts:
            raise ValueError(
                f"unknown ollama host alias {host_alias!r}; "
                f"configured: {sorted(hosts)}"
            )
        self._base_url = hosts[host_alias].rstrip("/")
        self._host_alias = host_alias
        self._model_tag = model_tag

    def __repr__(self) -> str:
        return (
            f"OllamaBackend(host={self._host_alias!r}, "
            f"model={self._model_tag!r})"
        )

    async def run(
        self, spec: AgentSpec, prompt: str, sink: EventSink
    ) -> None:
        sink.emit("status", {"status": "running"})
        body = {
            "model": self._model_tag,
            "stream": True,
            "messages": [
                {"role": "system", "content": spec.system_prompt},
                {"role": "user", "content": prompt},
            ],
            "options": {},
        }
        url = f"{self._base_url}/api/chat"
        timeout = aiohttp.ClientTimeout(total=spec.timeout_s)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body) as resp:
                    if resp.status >= 400:
                        sink.emit(
                            "error",
                            {"error": f"ollama request failed: status={resp.status}"},
                        )
                        raise RuntimeError(
                            f"ollama HTTP {resp.status} from {self._host_alias}"
                        )
                    async for line in resp.content:
                        line = line.strip()
                        if not line:
                            continue
                        _consume_line(line, sink)
        except aiohttp.ClientError as e:
            sink.emit("error", {"error": f"ollama network error: {type(e).__name__}"})
            raise
        except TimeoutError:
            sink.emit("error", {"error": f"ollama timeout after {spec.timeout_s}s"})
            raise


def _consume_line(line: bytes, sink: EventSink) -> None:
    try:
        chunk: dict[str, Any] = json.loads(line)
    except json.JSONDecodeError:
        return  # tolerate the rare keepalive/garbage line
    text = chunk.get("message", {}).get("content")
    if text:
        sink.emit("token", {"text": text})
    if chunk.get("done") is True:
        sink.emit("usage", normalize_usage("ollama", chunk, final=True))
