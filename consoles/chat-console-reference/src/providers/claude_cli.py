"""Claude CLI provider — subprocess wrapper around `claude --output-format stream-json`.

Session continuity:
  is_new_session=True  → `--session-id <uuid>` (creates session)
  is_new_session=False → `--resume <uuid>`     (continues session)

Same UUIDs work across console + terminal: `claude --resume <id>` from a
terminal in the same project bucket picks up where the console left off
(and vice versa). Project bucketing is by cwd, so the provider runs the
subprocess with cwd=CHAT_CONSOLE_WORKSPACE so console + terminal share state.

Translates [ENTERPRISE: cognitive engine vendor] stream-json events into TurnEvents:
  content_block_delta.text_delta → token
  content_block_start.tool_use   → tool_call
  user.tool_result               → tool_result

`AskUserQuestion` is disallowed (`--disallowed-tools`) because `claude
--print` short-circuits it internally (auto-resolves with "Question
cancelled"). Steering the model away from the tool keeps follow-up
questions as plain text, which the chat-console wire already handles —
the user answers in the next turn.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from turns import TurnBuffer, TurnEvent

from .base import Provider

logger = logging.getLogger(__name__)


# 64 KiB stdout reads + 10 MiB asyncio limit — large events from `claude`
# (full file contents in tool results) need headroom.
_READ_CHUNK = 64 * 1024
_PIPE_LIMIT = 10 * 1024 * 1024


class ClaudeCliProvider(Provider):
    """Subprocess `claude --output-format stream-json -p <prompt>`."""

    def __init__(
        self,
        binary: str = "claude",
        skip_permissions: bool = True,
        cwd: Optional[str] = None,
        extra_args: Optional[list[str]] = None,
    ):
        self.binary = binary
        self.skip_permissions = skip_permissions
        # Default cwd to CHAT_CONSOLE_WORKSPACE so console sessions land in the same Claude
        # Code project bucket as terminal sessions started from ~/chat-console.
        self.cwd = cwd if cwd is not None else os.environ.get("CHAT_CONSOLE_WORKSPACE")
        self.extra_args = list(extra_args) if extra_args else []

    def _build_cmd(self, prompt: str, session_id: str, is_new_session: bool) -> list[str]:
        cmd = [
            self.binary,
            "--output-format", "stream-json",
            "--include-partial-messages",  # token-by-token deltas, not full messages
            "--verbose",
            # AskUserQuestion is auto-resolved by --print; disallowing forces
            # the model to ask follow-ups inline, which fits the chat-console
            # turn-by-turn shape.
            "--disallowed-tools", "AskUserQuestion",
        ]
        if is_new_session:
            cmd.extend(["--session-id", session_id])
        else:
            cmd.extend(["--resume", session_id])
        cmd.extend(["-p", prompt])
        if self.skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        cmd.extend(self.extra_args)
        return cmd

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
            process = await asyncio.create_subprocess_exec(
                *self._build_cmd(prompt, session_id, is_new_session),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_PIPE_LIMIT,
                cwd=self.cwd,
            )
        except FileNotFoundError:
            await buf.finish(error=f"claude binary not found: {self.binary}")
            return
        except Exception as e:
            logger.exception("Failed to launch claude")
            await buf.finish(error=f"{type(e).__name__}: {e}")
            return

        try:
            await _parse_lines(process.stdout, buf)
            returncode = await process.wait()
            stderr_bytes = await process.stderr.read()
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()

            if returncode != 0:
                await buf.finish(
                    error=f"claude exited {returncode}: {stderr_text or '(no stderr)'}"
                )
                return
            await buf.finish()
        except Exception as e:
            logger.exception("Claude CLI parse/await error")
            await buf.finish(error=f"{type(e).__name__}: {e}")


async def _parse_lines(stream: asyncio.StreamReader, buf: TurnBuffer) -> None:
    """Read line-delimited JSON from `stream`, translating each event to a TurnEvent.

    Buffers across chunk boundaries so a partial JSON line at the end of one
    read concatenates with the start of the next. Malformed lines are skipped.

    Also threads a per-stream `state` dict through translation so we can
    accumulate tool-input fragments (`input_json_delta` events arrive between
    `content_block_start` and `content_block_stop` for each tool use).
    """
    state: dict = {"pending_tool_uses": {}, "pending_thinking": {}}
    pending = b""
    while True:
        chunk = await stream.read(_READ_CHUNK)
        if not chunk:
            break
        pending += chunk
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            await _consume_line(line, buf, state)
    # Final flush: trailing data with no newline still gets parsed.
    await _consume_line(pending, buf, state)


async def _consume_line(
    line: bytes, buf: TurnBuffer, state: Optional[dict] = None,
) -> None:
    line = line.strip()
    if not line:
        return
    try:
        event = json.loads(line.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        logger.debug("Skipping malformed JSON: %r", line[:200])
        return
    await _translate_event(event, buf, state)


async def _translate_event(
    event: dict, buf: TurnBuffer, state: Optional[dict] = None,
) -> None:
    """Map a claude stream-json event onto zero-or-more TurnEvent appends.

    With --include-partial-messages, the streaming-delta events arrive wrapped
    as `{"type":"stream_event","event":{...inner...}}`. Other top-level event
    shapes (`user`, `result`, `assistant`, `system`, `rate_limit_event`) come
    through directly.

    `state` is the per-stream parser state (carried by `_parse_lines`).
    Single-event callers (most tests) can omit it; we fall back to a fresh
    dict so the legacy "input present at content_block_start" path keeps
    working.
    """
    if state is None:
        state = {"pending_tool_uses": {}, "pending_thinking": {}}
    state.setdefault("pending_thinking", {})
    etype = event.get("type")
    # Phase A (#18): parent_tool_use_id is the wire-level signal that a
    # given event was tunneled through a subagent (Task tool). When set,
    # the renderer can nest the event under its parent's tool_call card;
    # when None, it's a direct event in the parent thread.
    parent_tool_use_id = event.get("parent_tool_use_id")

    # Unwrap stream_event → recurse on the inner [ENTERPRISE: cognitive engine vendor]-shaped event.
    if etype == "stream_event":
        inner = event.get("event") or {}
        await _translate_inner(inner, buf, state, parent_tool_use_id)
        return

    if etype == "user":
        message = event.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            for c in content:
                if not isinstance(c, dict):
                    continue
                ctype = c.get("type")
                if ctype == "tool_result":
                    await buf.append(
                        TurnEvent(
                            type="tool_result",
                            data={
                                "tool_use_id": c.get("tool_use_id"),
                                "content": c.get("content"),
                                "is_error": bool(c.get("is_error", False)),
                                "parent_tool_use_id": parent_tool_use_id,
                            },
                        )
                    )
                elif ctype == "text" and parent_tool_use_id is not None:
                    # Subagent's input prompt (and any interim input). Surface
                    # so the UI can show what was sent into the subagent under
                    # the parent's tool_call card. Parent-thread user messages
                    # don't take this path (parent_tool_use_id is null).
                    text = c.get("text") or ""
                    if text:
                        await buf.append(
                            TurnEvent(
                                type="subagent_text",
                                data={
                                    "text": text,
                                    "parent_tool_use_id": parent_tool_use_id,
                                },
                            )
                        )
        return

    if etype == "assistant":
        # Subagent's tool_uses + final text come through here, marked with
        # parent_tool_use_id. The parent-thread's own assistant events are
        # ALSO emitted here (parent_tool_use_id=None) but they're already
        # surfaced via the stream_event/content_block_* path with full
        # streamed input — emitting them again here would double-count.
        # So this branch only fires for non-null parent_tool_use_id.
        if parent_tool_use_id is None:
            return
        message = event.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            for c in content:
                if not isinstance(c, dict):
                    continue
                ctype = c.get("type")
                if ctype == "tool_use":
                    await buf.append(
                        TurnEvent(
                            type="tool_call",
                            data={
                                "id": c.get("id"),
                                "name": c.get("name"),
                                "input": c.get("input") or {},
                                "parent_tool_use_id": parent_tool_use_id,
                            },
                        )
                    )
                elif ctype == "text":
                    text = c.get("text") or ""
                    if text:
                        await buf.append(
                            TurnEvent(
                                type="subagent_text",
                                data={
                                    "text": text,
                                    "parent_tool_use_id": parent_tool_use_id,
                                },
                            )
                        )
        return

    if etype == "system":
        # Subagent lifecycle markers — surface so the UI can render
        # "● running" / "● complete" pills under the parent tool_call card.
        # `tool_use_id` here is the OUTER (parent-thread) Task tool_call id.
        subtype = event.get("subtype", "")
        if subtype in ("task_started", "task_progress", "task_notification"):
            await buf.append(
                TurnEvent(
                    type="task_event",
                    data={
                        "subtype": subtype,
                        "tool_use_id": event.get("tool_use_id"),
                        "task_id": event.get("task_id"),
                        "description": event.get("description"),
                        "status": event.get("status"),
                        "summary": event.get("summary"),
                        "last_tool_name": event.get("last_tool_name"),
                        "usage": event.get("usage"),
                    },
                )
            )
        # Other system subtypes (init/status/hook_*) intentionally ignored.
        return

    if etype == "result":
        # Final summary — extract authoritative usage + cost.
        usage = event.get("usage") or {}
        if usage:
            await buf.append(
                TurnEvent(type="usage", data=_usage_payload(usage, final=True, event=event))
            )
        return

    # rate_limit_event intentionally ignored.


async def _translate_inner(
    inner: dict,
    buf: TurnBuffer,
    state: dict,
    parent_tool_use_id: Optional[str] = None,
) -> None:
    """Translate an [ENTERPRISE: cognitive engine vendor]-shaped event (already unwrapped from stream_event).

    Tool-use lifecycle: `content_block_start` carries the tool id+name but
    NOT the full input — input arrives as a sequence of `content_block_delta`
    `input_json_delta` partials. We buffer those and emit a single complete
    `tool_call` on `content_block_stop`. `state["pending_tool_uses"]` is
    keyed by block index so concurrent blocks don't cross-contaminate.

    `parent_tool_use_id` propagates from the outer stream_event wrapper so
    each emitted tool_call carries the nesting signal (Phase A, #18).
    """
    itype = inner.get("type")
    block_index = inner.get("index", 0)

    if itype == "content_block_delta":
        delta = inner.get("delta") or {}
        dtype = delta.get("type")
        if dtype == "text_delta":
            text = delta.get("text", "")
            if text:
                await buf.append(TurnEvent(type="token", data={"text": text}))
        elif dtype == "input_json_delta":
            partial = delta.get("partial_json", "")
            pending = state["pending_tool_uses"].get(block_index)
            if pending is not None and partial:
                pending["input_json"] += partial
        elif dtype == "thinking_delta":
            chunk = delta.get("thinking", "")
            pending_t = state["pending_thinking"].get(block_index)
            if pending_t is not None and chunk:
                pending_t["text"] += chunk
        # signature_delta on thinking blocks (cryptographic signature) is
        # not surfaced — internal to Claude's verifiable-thinking feature.
        return

    if itype == "content_block_start":
        block = inner.get("content_block") or {}
        block_type = block.get("type")
        if block_type == "tool_use":
            # Buffer the tool_use so we can attach the streamed input.
            initial = block.get("input") or {}
            state["pending_tool_uses"][block_index] = {
                "id": block.get("id"),
                "name": block.get("name"),
                # Pre-seed input_json with any pre-streamed input (older claude
                # versions sent input here directly; current versions send {}).
                "input_json": json.dumps(initial) if initial else "",
                "parent_tool_use_id": parent_tool_use_id,
            }
        elif block_type == "thinking":
            # Buffer thinking deltas; flush as a single thinking event at
            # content_block_stop. Mirrors the tool_use buffer-then-emit
            # pattern so events stay interleaved correctly with tools/text.
            state["pending_thinking"][block_index] = {
                "text": "",
                "parent_tool_use_id": parent_tool_use_id,
            }
        return

    if itype == "content_block_stop":
        # Flush the buffered tool_use, if any, with the now-complete input.
        pending = state["pending_tool_uses"].pop(block_index, None)
        if pending is not None:
            input_json = pending.get("input_json", "")
            try:
                parsed_input = json.loads(input_json) if input_json else {}
            except json.JSONDecodeError:
                # Defensive: surface the raw fragments rather than crash so
                # the UI shows a tool_call even on a malformed delta sequence.
                parsed_input = {"_raw": input_json}
            await buf.append(
                TurnEvent(
                    type="tool_call",
                    data={
                        "id": pending["id"],
                        "name": pending["name"],
                        "input": parsed_input,
                        "parent_tool_use_id": pending.get("parent_tool_use_id"),
                    },
                )
            )
        # Flush a thinking block, if any. Empty thinking blocks (no deltas
        # arrived between start and stop) are dropped — nothing to render.
        pending_t = state["pending_thinking"].pop(block_index, None)
        if pending_t is not None and pending_t["text"]:
            await buf.append(
                TurnEvent(
                    type="thinking",
                    data={
                        "text": pending_t["text"],
                        "parent_tool_use_id": pending_t.get("parent_tool_use_id"),
                    },
                )
            )
        return

    if itype == "message_delta":
        usage = inner.get("usage") or {}
        if usage:
            await buf.append(
                TurnEvent(type="usage", data=_usage_payload(usage, final=False))
            )
        return

    # message_start / message_stop intentionally ignored.


def _usage_payload(usage: dict, *, final: bool, event: Optional[dict] = None) -> dict:
    """Normalize a usage block into a flat shape consumable by the session registry.

    `total_input_tokens` includes the prompt-cache contributions because that's
    what determines context-window utilization (the field claude calls
    `input_tokens` is just the *new* portion, post-cache-hit).
    """
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
