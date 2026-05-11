"""ClaudeCliBackend — uses the local `claude` CLI as the model engine.

Reuses JD's [ENTERPRISE: cognitive engine CLI] subscription auth — no API key. Subprocess shape
mirrors `console/providers/claude_cli.py` from #15: `claude -p <prompt>
--system-prompt <spec.system_prompt> --model <spec.model>
--output-format stream-json --include-partial-messages` produces SSE-shaped
stdout that we parse line-by-line and translate into TurnEvents on the sink.

Phase 1 default; Phase 6 adds OpenAI / Gemini / Ollama API-direct backends
that don't need `claude`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from ..specs.model import AgentSpec

from .backend import AgentBackend
from .fork_defaults import disallowed_for, resolve_tools
from .sink import EventSink


logger = logging.getLogger(__name__)


_PIPE_LIMIT = 10 * 1024 * 1024  # 10 MiB — large tool_result blobs need headroom
_READ_CHUNK = 64 * 1024


class ClaudeCliBackend(AgentBackend):
    """Subprocess wrap of `claude -p`."""

    def __init__(
        self,
        binary: str = "claude",
        skip_permissions: bool = True,
        cwd: Optional[str] = None,
        extra_args: Optional[list[str]] = None,
    ):
        self.binary = binary
        self.skip_permissions = skip_permissions
        self.cwd = cwd
        self.extra_args = list(extra_args) if extra_args else []

    def _build_cmd(self, spec: AgentSpec, prompt: str) -> list[str]:
        cmd = [
            self.binary,
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--system-prompt", spec.system_prompt,
            "--model", spec.model,
            "-p", prompt,
        ]
        # Phase 2: enforce per-spec capability scoping. R1 verification showed
        # `--allowedTools` is auto-approve only; `--disallowedTools` is what
        # actually removes tools from the agent's set. We always pass the
        # complement so the agent sees ONLY the allowlist (resolved through
        # fork defaults when spec.tools is None; explicit [] = no tools).
        allowed = resolve_tools(spec)
        denied = disallowed_for(allowed)
        if denied:
            cmd.extend(["--disallowedTools", " ".join(denied)])
        if self.skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        cmd.extend(self.extra_args)
        return cmd

    async def run(
        self, spec: AgentSpec, prompt: str, sink: EventSink
    ) -> None:
        sink.emit("status", {"status": "running"})

        # cwd resolution priority: spec.cwd → backend's self.cwd (per-run
        # workspace from the daemon) → None (process default).
        effective_cwd = spec.cwd or self.cwd

        try:
            process = await asyncio.create_subprocess_exec(
                *self._build_cmd(spec, prompt),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_PIPE_LIMIT,
                cwd=effective_cwd,
            )
        except FileNotFoundError:
            sink.emit("error", {"error": f"claude binary not found: {self.binary}"})
            raise RuntimeError(f"claude binary not found: {self.binary}")

        try:
            await _parse_lines(process.stdout, sink)
            returncode = await process.wait()
            stderr_bytes = await process.stderr.read()
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
            if returncode != 0:
                err = f"claude exited {returncode}: {stderr_text or '(no stderr)'}"
                sink.emit("error", {"exit_code": returncode, "stderr": stderr_text[:500]})
                raise RuntimeError(err)
        except asyncio.CancelledError:
            process.terminate()
            raise


async def _parse_lines(
    stream: asyncio.StreamReader, sink: EventSink
) -> None:
    """Read line-delimited JSON from stdout, translating to TurnEvents.
    Buffers across chunk boundaries; malformed JSON skipped."""
    pending = b""
    while True:
        chunk = await stream.read(_READ_CHUNK)
        if not chunk:
            break
        pending += chunk
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            _consume_line(line, sink)
    _consume_line(pending, sink)


def _consume_line(line: bytes, sink: EventSink) -> None:
    line = line.strip()
    if not line:
        return
    try:
        event = json.loads(line.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return
    _translate_event(event, sink)


def _translate_event(event: dict, sink: EventSink) -> None:
    """Map a single claude stream-json event onto zero-or-more sink emits.

    With --include-partial-messages, streaming-delta events arrive wrapped:
        {"type": "stream_event", "event": {<inner [ENTERPRISE: cognitive engine vendor] event>}}
    Other top-level shapes (`user`, `result`, `assistant`, `system`,
    `rate_limit_event`) come through directly. Phase 1 surfaces token
    + usage; tool_use/tool_result handling lands in Phase 2.
    """
    etype = event.get("type")

    if etype == "stream_event":
        inner = event.get("event") or {}
        _translate_inner(inner, sink)
        return

    if etype == "result":
        # Final summary — authoritative usage + cost.
        usage = event.get("usage") or {}
        if usage:
            sink.emit("usage", _usage_payload(usage, final=True, event=event))
        return

    if etype == "user":
        # Tool results come back as a user message with tool_result content
        # blocks. (Phase 2: surface them; mirrors console/providers/claude_cli.py
        # so the existing fleet UI run-modal renders them without UI changes.)
        message = event.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    sink.emit(
                        "tool_result",
                        {
                            "tool_use_id": c.get("tool_use_id"),
                            "content": c.get("content"),
                            "is_error": bool(c.get("is_error", False)),
                        },
                    )
        return

    # system / assistant / rate_limit_event — intentionally skipped.


def _translate_inner(inner: dict, sink: EventSink) -> None:
    itype = inner.get("type")

    if itype == "content_block_delta":
        delta = inner.get("delta") or {}
        if delta.get("type") == "text_delta":
            text = delta.get("text", "")
            if text:
                sink.emit("token", {"text": text})
        return

    if itype == "message_delta":
        usage = inner.get("usage") or {}
        if usage:
            sink.emit("usage", _usage_payload(usage, final=False))
        return

    if itype == "content_block_start":
        # Tool invocations: agent emits content_block_start with
        # content_block.type == "tool_use" before streaming the input JSON.
        block = inner.get("content_block") or {}
        if block.get("type") == "tool_use":
            sink.emit(
                "tool_call",
                {
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "input": block.get("input") or {},
                },
            )
        return

    # message_start / content_block_stop / message_stop / ping —
    # not surfaced in Phase 1/2.


def _usage_payload(
    usage: dict, *, final: bool, event: Optional[dict] = None
) -> dict:
    """Normalize a usage block into a flat shape consumable by the UI.
    `total_input_tokens` includes prompt-cache contributions because
    that's what determines context-window utilization."""
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    cache_creation = int(usage.get("cache_creation_input_tokens", 0) or 0)
    cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    payload = {
        "input_tokens": input_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "output_tokens": output_tokens,
        "total_input_tokens": input_tokens + cache_creation + cache_read,
        "final": final,
    }
    if event is not None:
        cost = event.get("total_cost_usd")
        if cost is not None:
            payload["total_cost_usd"] = float(cost)
    return payload
