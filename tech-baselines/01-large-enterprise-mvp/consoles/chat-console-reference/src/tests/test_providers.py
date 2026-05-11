"""Tests for providers/. Coverage:
- ClaudeCliProvider command construction (default + skip-permissions off + extra args)
- Event translation (text_delta → token, tool_use → tool_call, tool_result)
- Line buffering across chunk boundaries; malformed JSON skipped
- End-to-end with mocked subprocess (success + non-zero exit + missing binary)
- Factory: make_provider default / explicit / unknown.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from providers import ClaudeCliProvider, Provider, make_provider
from providers.claude_cli import _parse_lines, _translate_event
from turns import TurnBuffer, TurnStatus


# ---------- command construction ----------


def test_build_cmd_new_session_uses_session_id_flag():
    cmd = ClaudeCliProvider()._build_cmd("hello", "uuid-A", is_new_session=True)
    assert cmd[0] == "claude"
    assert "--output-format" in cmd
    assert "stream-json" in cmd
    assert "--verbose" in cmd
    # New session creates with --session-id
    assert "--session-id" in cmd
    assert cmd[cmd.index("--session-id") + 1] == "uuid-A"
    assert "--resume" not in cmd
    assert cmd[cmd.index("-p") + 1] == "hello"
    assert "--dangerously-skip-permissions" in cmd


def test_build_cmd_existing_session_uses_resume():
    cmd = ClaudeCliProvider()._build_cmd("follow up", "uuid-A", is_new_session=False)
    assert "--resume" in cmd
    assert cmd[cmd.index("--resume") + 1] == "uuid-A"
    assert "--session-id" not in cmd


def test_build_cmd_skip_permissions_off():
    cmd = ClaudeCliProvider(skip_permissions=False)._build_cmd(
        "hi", "uuid-A", is_new_session=True
    )
    assert "--dangerously-skip-permissions" not in cmd


def test_build_cmd_custom_binary_and_extra_args():
    p = ClaudeCliProvider(binary="/opt/bin/claude", extra_args=["--model", "haiku"])
    cmd = p._build_cmd("hi", "uuid-A", is_new_session=True)
    assert cmd[0] == "/opt/bin/claude"
    assert "--model" in cmd
    assert "haiku" in cmd


def test_provider_cwd_defaults_to_workspace_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CHAT_CONSOLE_WORKSPACE", str(tmp_path))
    p = ClaudeCliProvider()
    assert p.cwd == str(tmp_path)


def test_provider_cwd_explicit_overrides_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CHAT_CONSOLE_WORKSPACE", "/should/not/win")
    p = ClaudeCliProvider(cwd=str(tmp_path))
    assert p.cwd == str(tmp_path)


def test_provider_cwd_none_when_unset(monkeypatch):
    monkeypatch.delenv("CHAT_CONSOLE_WORKSPACE", raising=False)
    p = ClaudeCliProvider()
    assert p.cwd is None


# ---------- event translation ----------


@pytest.fixture
async def started_buf(tmp_path: Path) -> TurnBuffer:
    buf = TurnBuffer(turn_id="t", data_dir=tmp_path)
    await buf.start()
    return buf


def _stream_event(inner: dict) -> dict:
    """Wrap an [ENTERPRISE: cognitive engine vendor]-shaped event the way claude --include-partial-messages does."""
    return {"type": "stream_event", "event": inner, "session_id": "X"}


async def test_translate_text_delta(started_buf: TurnBuffer):
    await _translate_event(
        _stream_event(
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}
        ),
        started_buf,
    )
    assert started_buf.event_count == 1
    parsed = json.loads(started_buf._events[0])
    assert parsed["type"] == "token"
    assert parsed["data"]["text"] == "hi"


async def test_translate_text_delta_empty_skipped(started_buf: TurnBuffer):
    await _translate_event(
        _stream_event(
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": ""}}
        ),
        started_buf,
    )
    assert started_buf.event_count == 0


async def test_translate_non_text_delta_skipped(started_buf: TurnBuffer):
    await _translate_event(
        _stream_event(
            {
                "type": "content_block_delta",
                "delta": {"type": "input_json_delta", "partial_json": "{"},
            }
        ),
        started_buf,
    )
    assert started_buf.event_count == 0


async def test_translate_tool_use_legacy_inline_input(started_buf: TurnBuffer):
    """Legacy path: content_block_start carries the full input AND the
    block_stop arrives in the same translation context. Some older claude
    versions did this; we still support it."""
    state: dict = {"pending_tool_uses": {}}
    await _translate_event(
        _stream_event(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "T1",
                    "name": "bash",
                    "input": {"cmd": "ls"},
                },
            }
        ),
        started_buf, state,
    )
    # Nothing emitted yet — we always wait for content_block_stop.
    assert started_buf.event_count == 0
    await _translate_event(
        _stream_event({"type": "content_block_stop", "index": 0}),
        started_buf, state,
    )
    assert started_buf.event_count == 1
    parsed = json.loads(started_buf._events[0])
    assert parsed["type"] == "tool_call"
    assert parsed["data"] == {
        "id": "T1", "name": "bash", "input": {"cmd": "ls"},
        "parent_tool_use_id": None,
    }


async def test_translate_tool_use_streamed_input(started_buf: TurnBuffer):
    """Current claude path: content_block_start carries empty input,
    input_json_delta events stream the JSON in fragments, content_block_stop
    triggers emission of the complete tool_call."""
    state: dict = {"pending_tool_uses": {}}
    # 1) start: tool_use header, empty input
    await _translate_event(
        _stream_event(
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_X",
                    "name": "Glob",
                    "input": {},
                },
            }
        ),
        started_buf, state,
    )
    assert started_buf.event_count == 0  # buffered, not emitted

    # 2) input streamed across multiple deltas
    for partial in ('{"pattern": "console/**/*.py', '"}'):
        await _translate_event(
            _stream_event(
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": partial},
                }
            ),
            started_buf, state,
        )
    assert started_buf.event_count == 0  # still buffered

    # 3) stop emits the complete tool_call
    await _translate_event(
        _stream_event({"type": "content_block_stop", "index": 1}),
        started_buf, state,
    )
    assert started_buf.event_count == 1
    parsed = json.loads(started_buf._events[0])
    assert parsed["type"] == "tool_call"
    assert parsed["data"] == {
        "id": "toolu_X", "name": "Glob",
        "input": {"pattern": "console/**/*.py"},
        "parent_tool_use_id": None,
    }


async def test_translate_tool_use_malformed_json_falls_back_to_raw(started_buf: TurnBuffer):
    """If the streamed JSON is malformed (truncated stream, etc.), surface
    the raw partial under `_raw` rather than dropping the tool_call entirely."""
    state: dict = {"pending_tool_uses": {}}
    await _translate_event(
        _stream_event(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use", "id": "T", "name": "Bash", "input": {},
                },
            }
        ),
        started_buf, state,
    )
    await _translate_event(
        _stream_event(
            {
                "type": "content_block_delta", "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '{"cmd": "ls'},
            }
        ),
        started_buf, state,
    )
    await _translate_event(
        _stream_event({"type": "content_block_stop", "index": 0}),
        started_buf, state,
    )
    assert started_buf.event_count == 1
    parsed = json.loads(started_buf._events[0])
    assert parsed["type"] == "tool_call"
    assert parsed["data"]["input"] == {"_raw": '{"cmd": "ls'}


async def test_translate_concurrent_tool_uses_no_cross_contamination(started_buf: TurnBuffer):
    """Two parallel tool_use blocks (different indices) must not have their
    input fragments mix."""
    state: dict = {"pending_tool_uses": {}}
    # Start two blocks
    for idx, name in ((0, "Glob"), (1, "Read")):
        await _translate_event(
            _stream_event(
                {
                    "type": "content_block_start", "index": idx,
                    "content_block": {
                        "type": "tool_use", "id": f"T{idx}", "name": name, "input": {},
                    },
                }
            ),
            started_buf, state,
        )
    # Interleave fragments
    fragments = [
        (0, '{"pattern": "*.py'),
        (1, '{"file_path": "/etc'),
        (0, '"}'),
        (1, '/hostname"}'),
    ]
    for idx, frag in fragments:
        await _translate_event(
            _stream_event(
                {
                    "type": "content_block_delta", "index": idx,
                    "delta": {"type": "input_json_delta", "partial_json": frag},
                }
            ),
            started_buf, state,
        )
    # Stop block 0 first, then block 1
    await _translate_event(
        _stream_event({"type": "content_block_stop", "index": 0}),
        started_buf, state,
    )
    await _translate_event(
        _stream_event({"type": "content_block_stop", "index": 1}),
        started_buf, state,
    )
    assert started_buf.event_count == 2
    e0 = json.loads(started_buf._events[0])
    e1 = json.loads(started_buf._events[1])
    assert e0["data"]["name"] == "Glob"
    assert e0["data"]["input"] == {"pattern": "*.py"}
    assert e1["data"]["name"] == "Read"
    assert e1["data"]["input"] == {"file_path": "/etc/hostname"}


async def test_translate_thinking_block_emits_thinking_event(started_buf: TurnBuffer):
    """Extended-thinking wire path: content_block_start.thinking → buffered;
    thinking_delta accumulates; content_block_stop emits one `thinking`
    TurnEvent with full text. Mirrors the tool_use buffer-then-emit pattern."""
    state: dict = {"pending_tool_uses": {}, "pending_thinking": {}}

    # 1) start: thinking block opens, no event yet
    await _translate_event(
        _stream_event(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": ""},
            }
        ),
        started_buf, state,
    )
    assert started_buf.event_count == 0

    # 2) deltas stream the reasoning
    for chunk in ("Let me think. ", "First, I need to ", "check the inputs."):
        await _translate_event(
            _stream_event(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "thinking_delta", "thinking": chunk},
                }
            ),
            started_buf, state,
        )
    assert started_buf.event_count == 0  # still buffered

    # 3) signature_delta is intentionally ignored (not surfaced)
    await _translate_event(
        _stream_event(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "abc123"},
            }
        ),
        started_buf, state,
    )
    assert started_buf.event_count == 0

    # 4) stop emits the complete thinking event
    await _translate_event(
        _stream_event({"type": "content_block_stop", "index": 0}),
        started_buf, state,
    )
    assert started_buf.event_count == 1
    parsed = json.loads(started_buf._events[0])
    assert parsed["type"] == "thinking"
    assert parsed["data"]["text"] == "Let me think. First, I need to check the inputs."
    assert parsed["data"]["parent_tool_use_id"] is None


async def test_translate_thinking_block_empty_dropped(started_buf: TurnBuffer):
    """Empty thinking block (no deltas) → no event emitted (nothing to render)."""
    state: dict = {"pending_tool_uses": {}, "pending_thinking": {}}
    await _translate_event(
        _stream_event(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": ""},
            }
        ),
        started_buf, state,
    )
    await _translate_event(
        _stream_event({"type": "content_block_stop", "index": 0}),
        started_buf, state,
    )
    assert started_buf.event_count == 0


async def test_translate_thinking_interleaved_with_tool_use(started_buf: TurnBuffer):
    """Real-world ordering: think → tool_call → think → answer. Each thinking
    and tool event must appear in event-order, not coalesce."""
    state: dict = {"pending_tool_uses": {}, "pending_thinking": {}}

    # think block #0
    await _translate_event(
        _stream_event({
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "thinking", "thinking": ""},
        }),
        started_buf, state,
    )
    await _translate_event(
        _stream_event({
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "first thought"},
        }),
        started_buf, state,
    )
    await _translate_event(
        _stream_event({"type": "content_block_stop", "index": 0}),
        started_buf, state,
    )

    # tool block #1
    await _translate_event(
        _stream_event({
            "type": "content_block_start", "index": 1,
            "content_block": {"type": "tool_use", "id": "T1", "name": "bash", "input": {"cmd": "ls"}},
        }),
        started_buf, state,
    )
    await _translate_event(
        _stream_event({"type": "content_block_stop", "index": 1}),
        started_buf, state,
    )

    # think block #2
    await _translate_event(
        _stream_event({
            "type": "content_block_start", "index": 2,
            "content_block": {"type": "thinking", "thinking": ""},
        }),
        started_buf, state,
    )
    await _translate_event(
        _stream_event({
            "type": "content_block_delta", "index": 2,
            "delta": {"type": "thinking_delta", "thinking": "second thought"},
        }),
        started_buf, state,
    )
    await _translate_event(
        _stream_event({"type": "content_block_stop", "index": 2}),
        started_buf, state,
    )

    types = [json.loads(e)["type"] for e in started_buf._events]
    assert types == ["thinking", "tool_call", "thinking"]
    payloads = [json.loads(e)["data"] for e in started_buf._events]
    assert payloads[0]["text"] == "first thought"
    assert payloads[1]["name"] == "bash"
    assert payloads[2]["text"] == "second thought"


async def test_translate_content_block_start_text_skipped(started_buf: TurnBuffer):
    await _translate_event(
        _stream_event(
            {
                "type": "content_block_start",
                "content_block": {"type": "text", "text": ""},
            }
        ),
        started_buf,
    )
    assert started_buf.event_count == 0


async def test_translate_message_delta_emits_usage(started_buf: TurnBuffer):
    await _translate_event(
        _stream_event(
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {
                    "input_tokens": 4,
                    "cache_creation_input_tokens": 1500,
                    "cache_read_input_tokens": 12000,
                    "output_tokens": 7,
                },
            }
        ),
        started_buf,
    )
    assert started_buf.event_count == 1
    parsed = json.loads(started_buf._events[0])
    assert parsed["type"] == "usage"
    assert parsed["data"]["total_input_tokens"] == 4 + 1500 + 12000
    assert parsed["data"]["output_tokens"] == 7
    assert parsed["data"]["final"] is False


async def test_translate_result_emits_final_usage_with_cost(started_buf: TurnBuffer):
    await _translate_event(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "usage": {
                "input_tokens": 4,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 13500,
                "output_tokens": 12,
            },
            "total_cost_usd": 0.05,
        },
        started_buf,
    )
    parsed = json.loads(started_buf._events[0])
    assert parsed["type"] == "usage"
    assert parsed["data"]["final"] is True
    assert parsed["data"]["total_cost_usd"] == 0.05
    assert parsed["data"]["total_input_tokens"] == 13504


async def test_translate_tool_result(started_buf: TurnBuffer):
    await _translate_event(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "T1",
                        "content": "ok",
                        "is_error": False,
                    }
                ]
            },
        },
        started_buf,
    )
    assert started_buf.event_count == 1
    parsed = json.loads(started_buf._events[0])
    assert parsed["type"] == "tool_result"
    assert parsed["data"]["tool_use_id"] == "T1"
    assert parsed["data"]["is_error"] is False


async def test_translate_tool_result_error_flag(started_buf: TurnBuffer):
    await _translate_event(
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "T2", "content": "boom", "is_error": True}
                ]
            },
        },
        started_buf,
    )
    parsed = json.loads(started_buf._events[0])
    assert parsed["data"]["is_error"] is True


async def test_translate_unknown_event_skipped(started_buf: TurnBuffer):
    await _translate_event({"type": "system", "message": "init"}, started_buf)
    await _translate_event({"type": "result", "result": "done"}, started_buf)
    assert started_buf.event_count == 0


# ---------- _parse_lines (StreamReader → events) ----------


async def _make_stream(data: bytes) -> asyncio.StreamReader:
    r = asyncio.StreamReader()
    r.feed_data(data)
    r.feed_eof()
    return r


def _wrapped_token_line(text: str) -> bytes:
    """One JSONL line in real-claude shape: stream_event wrapping content_block_delta."""
    return (
        b'{"type":"stream_event","event":{"type":"content_block_delta",'
        b'"delta":{"type":"text_delta","text":"' + text.encode() + b'"}}}\n'
    )


async def test_parse_lines_multiple_events(started_buf: TurnBuffer):
    payload = _wrapped_token_line("hello ") + _wrapped_token_line("world")
    await _parse_lines(await _make_stream(payload), started_buf)
    assert started_buf.event_count == 2


async def test_parse_lines_skips_malformed(started_buf: TurnBuffer):
    payload = _wrapped_token_line("a") + b"this is not json\n" + _wrapped_token_line("b")
    await _parse_lines(await _make_stream(payload), started_buf)
    assert started_buf.event_count == 2


async def test_parse_lines_handles_split_chunks(started_buf: TurnBuffer):
    """Event split across read chunks — the parser must accumulate."""
    reader = asyncio.StreamReader()
    reader.feed_data(
        b'{"type":"stream_event","event":{"type":"content_block_delta",'
        b'"delta":{"type":"text_delta","text":"split'
    )
    reader.feed_data(b' message"}}}\n')
    reader.feed_eof()
    await _parse_lines(reader, started_buf)
    assert started_buf.event_count == 1
    parsed = json.loads(started_buf._events[0])
    assert parsed["data"]["text"] == "split message"


async def test_parse_lines_final_buffer_without_newline(started_buf: TurnBuffer):
    payload = _wrapped_token_line("a").rstrip(b"\n")  # no trailing newline
    await _parse_lines(await _make_stream(payload), started_buf)
    assert started_buf.event_count == 1


async def test_parse_lines_ignores_blank_lines(started_buf: TurnBuffer):
    payload = b"\n\n" + _wrapped_token_line("a") + b"\n\n"
    await _parse_lines(await _make_stream(payload), started_buf)
    assert started_buf.event_count == 1


# ---------- end-to-end with mocked subprocess ----------


class _FakeProcess:
    """Stand-in for asyncio.subprocess.Process; minimal surface used by the provider."""

    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0):
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stdout.feed_eof()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_data(stderr)
        self.stderr.feed_eof()
        self.returncode = returncode

    async def wait(self) -> int:
        return self.returncode


async def test_provider_end_to_end_success(tmp_path: Path):
    buf = TurnBuffer(turn_id="t", data_dir=tmp_path)
    fake = _FakeProcess(
        stdout=(
            b'{"type":"stream_event","event":{"type":"content_block_delta",'
            b'"delta":{"type":"text_delta","text":"hi"}}}\n'
            b'{"type":"result","subtype":"success","is_error":false,'
            b'"usage":{"input_tokens":4,"cache_read_input_tokens":1000,"output_tokens":1},'
            b'"total_cost_usd":0.01}\n'
        ),
    )
    with patch(
        "providers.claude_cli.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    ):
        await ClaudeCliProvider()(buf, "say hi", session_id="uuid-A", is_new_session=True)
    assert buf.status == TurnStatus.DONE
    assert buf.error is None
    # 1 token + 1 final usage event
    assert buf.event_count == 2


async def test_provider_nonzero_exit_sets_error(tmp_path: Path):
    buf = TurnBuffer(turn_id="t", data_dir=tmp_path)
    fake = _FakeProcess(stdout=b"", stderr=b"boom\n", returncode=1)
    with patch(
        "providers.claude_cli.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    ):
        await ClaudeCliProvider()(buf, "x", session_id="uuid-A", is_new_session=True)
    assert buf.status == TurnStatus.ERROR
    assert "1" in buf.error
    assert "boom" in buf.error


async def test_provider_binary_missing(tmp_path: Path):
    buf = TurnBuffer(turn_id="t", data_dir=tmp_path)
    with patch(
        "providers.claude_cli.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=FileNotFoundError()),
    ):
        await ClaudeCliProvider(binary="/nope/claude")(
            buf, "x", session_id="uuid-A", is_new_session=True
        )
    assert buf.status == TurnStatus.ERROR
    assert "not found" in buf.error


async def test_provider_unexpected_launch_exception(tmp_path: Path):
    buf = TurnBuffer(turn_id="t", data_dir=tmp_path)
    with patch(
        "providers.claude_cli.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=PermissionError("denied")),
    ):
        await ClaudeCliProvider()(buf, "x", session_id="uuid-A", is_new_session=True)
    assert buf.status == TurnStatus.ERROR
    assert "PermissionError" in buf.error


async def test_provider_resume_passes_resume_flag(tmp_path: Path):
    """Subsequent turns of an existing session use --resume, not --session-id."""
    captured_cmd: list[list] = []

    async def fake_exec(*args, **kwargs):
        captured_cmd.append(list(args))
        return _FakeProcess(stdout=b"", returncode=0)

    buf = TurnBuffer(turn_id="t", data_dir=tmp_path)
    with patch(
        "providers.claude_cli.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=fake_exec),
    ):
        await ClaudeCliProvider()(
            buf, "follow up", session_id="uuid-X", is_new_session=False
        )
    assert len(captured_cmd) == 1
    cmd = captured_cmd[0]
    assert "--resume" in cmd
    assert "uuid-X" in cmd
    assert "--session-id" not in cmd


async def test_provider_invokes_subprocess_with_cwd(tmp_path: Path, monkeypatch):
    """Provider passes cwd= so claude lands in the CHAT_CONSOLE_WORKSPACE project bucket
    (shared with terminal sessions started from the same cwd)."""
    monkeypatch.setenv("CHAT_CONSOLE_WORKSPACE", str(tmp_path))
    captured_kwargs: list[dict] = []

    async def fake_exec(*args, **kwargs):
        captured_kwargs.append(kwargs)
        return _FakeProcess(stdout=b"", returncode=0)

    buf = TurnBuffer(turn_id="t", data_dir=tmp_path)
    with patch(
        "providers.claude_cli.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=fake_exec),
    ):
        await ClaudeCliProvider()(
            buf, "x", session_id="uuid-A", is_new_session=True
        )
    assert captured_kwargs[0]["cwd"] == str(tmp_path)


# ---------- factory ----------


def test_make_provider_default(monkeypatch):
    monkeypatch.delenv("[ENTERPRISE: env var]", raising=False)
    assert isinstance(make_provider(), ClaudeCliProvider)


def test_make_provider_explicit():
    assert isinstance(make_provider("claude-cli"), ClaudeCliProvider)


def test_make_provider_reads_env(monkeypatch):
    monkeypatch.setenv("[ENTERPRISE: env var]", "claude-cli")
    assert isinstance(make_provider(), ClaudeCliProvider)


def test_make_provider_unknown_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        make_provider("does-not-exist")


def test_provider_is_abstract():
    """Provider can't be instantiated directly."""
    with pytest.raises(TypeError):
        Provider()  # type: ignore[abstract]


# ---------- Phase A (#18): subagent + lifecycle events ----------
#
# Wire-format fixtures are verbatim from a captured `claude --output-format
# stream-json --include-partial-messages` run with a Task tool prompt. See
# /tmp/raw-task-stream.txt for the full capture; the relevant shapes are
# embedded inline so the tests are self-contained.


async def test_translate_assistant_subagent_tool_use(started_buf: TurnBuffer):
    """A subagent's inner tool_use comes through as a top-level `assistant`
    event with `parent_tool_use_id` pointing at the outer Task call. We
    emit it as a tool_call carrying the parent linkage so the renderer
    can nest it under the Task card."""
    await _translate_event(
        {
            "type": "assistant",
            "parent_tool_use_id": "toolu_OUTER",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_INNER",
                        "name": "Bash",
                        "input": {"command": "find . -name '*.py'"},
                    }
                ]
            },
        },
        started_buf,
    )
    assert started_buf.event_count == 1
    parsed = json.loads(started_buf._events[0])
    assert parsed["type"] == "tool_call"
    assert parsed["data"] == {
        "id": "toolu_INNER",
        "name": "Bash",
        "input": {"command": "find . -name '*.py'"},
        "parent_tool_use_id": "toolu_OUTER",
    }


async def test_translate_assistant_parent_thread_skipped(started_buf: TurnBuffer):
    """Parent-thread assistant events (parent_tool_use_id=None) come through
    too, but they're already surfaced via the stream_event/content_block_*
    path with full streamed input — emitting again here would double-count.
    Skip them in this branch."""
    await _translate_event(
        {
            "type": "assistant",
            "parent_tool_use_id": None,
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_PARENT",
                        "name": "Agent",
                        "input": {"description": "x"},
                    }
                ]
            },
        },
        started_buf,
    )
    assert started_buf.event_count == 0


async def test_translate_assistant_subagent_text(started_buf: TurnBuffer):
    """Subagent's final text response (the message it returns to the parent)
    arrives in an assistant event with parent_tool_use_id set. Emit as
    `subagent_text` so the renderer can show it inline under the Task card."""
    await _translate_event(
        {
            "type": "assistant",
            "parent_tool_use_id": "toolu_OUTER",
            "message": {
                "content": [
                    {"type": "text", "text": "Found 3 .py files: a, b, c."}
                ]
            },
        },
        started_buf,
    )
    assert started_buf.event_count == 1
    parsed = json.loads(started_buf._events[0])
    assert parsed["type"] == "subagent_text"
    assert parsed["data"] == {
        "text": "Found 3 .py files: a, b, c.",
        "parent_tool_use_id": "toolu_OUTER",
    }


async def test_translate_user_text_with_parent_tool_use_id(started_buf: TurnBuffer):
    """The subagent's input prompt arrives as a top-level `user` event with
    a text content block + parent_tool_use_id. Surface as subagent_text
    so the UI can show what was sent INTO the subagent."""
    await _translate_event(
        {
            "type": "user",
            "parent_tool_use_id": "toolu_OUTER",
            "message": {
                "content": [
                    {"type": "text", "text": "Count .py files in console/"}
                ]
            },
        },
        started_buf,
    )
    assert started_buf.event_count == 1
    parsed = json.loads(started_buf._events[0])
    assert parsed["type"] == "subagent_text"
    assert parsed["data"]["text"] == "Count .py files in console/"
    assert parsed["data"]["parent_tool_use_id"] == "toolu_OUTER"


async def test_translate_user_text_at_parent_thread_ignored(started_buf: TurnBuffer):
    """A text content block in a top-level user event WITHOUT
    parent_tool_use_id is not an event we surface — that's the parent's
    own user message, which the chat already knows about (the user typed
    it). Only subagent-tunneled text gets emitted."""
    await _translate_event(
        {
            "type": "user",
            "parent_tool_use_id": None,
            "message": {
                "content": [{"type": "text", "text": "the user's prompt"}]
            },
        },
        started_buf,
    )
    assert started_buf.event_count == 0


async def test_translate_user_tool_result_carries_parent_tool_use_id(
    started_buf: TurnBuffer,
):
    """Existing tool_result emission now also carries parent_tool_use_id so
    the renderer can group subagent-internal results under the Task card."""
    await _translate_event(
        {
            "type": "user",
            "parent_tool_use_id": "toolu_OUTER",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_INNER",
                        "content": "found 3 files",
                        "is_error": False,
                    }
                ]
            },
        },
        started_buf,
    )
    parsed = json.loads(started_buf._events[0])
    assert parsed["type"] == "tool_result"
    assert parsed["data"]["parent_tool_use_id"] == "toolu_OUTER"
    assert parsed["data"]["tool_use_id"] == "toolu_INNER"


async def test_translate_user_tool_result_top_level_has_null_parent(
    started_buf: TurnBuffer,
):
    """Parent-thread tool_results (Task tool returning to parent) carry
    parent_tool_use_id=None — explicit null, so the renderer can know
    to render them at the top level."""
    await _translate_event(
        {
            "type": "user",
            "parent_tool_use_id": None,
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_OUTER",
                        "content": "subagent's final output",
                        "is_error": False,
                    }
                ]
            },
        },
        started_buf,
    )
    parsed = json.loads(started_buf._events[0])
    assert parsed["data"]["parent_tool_use_id"] is None


async def test_translate_system_task_started(started_buf: TurnBuffer):
    """system.task_started is the lifecycle marker [ENTERPRISE: cognitive engine CLI] uses to
    show "● running" pills under the parent Task card. We surface it as
    `task_event` carrying the OUTER tool_use_id so the renderer can
    attach it to the right card."""
    await _translate_event(
        {
            "type": "system",
            "subtype": "task_started",
            "task_id": "ab3b994f72c56c517",
            "tool_use_id": "toolu_OUTER",
            "description": "Count .py files",
            "task_type": "local_agent",
            "prompt": "Count the number of .py files in console/.",
        },
        started_buf,
    )
    parsed = json.loads(started_buf._events[0])
    assert parsed["type"] == "task_event"
    assert parsed["data"]["subtype"] == "task_started"
    assert parsed["data"]["tool_use_id"] == "toolu_OUTER"
    assert parsed["data"]["description"] == "Count .py files"


async def test_translate_system_task_progress(started_buf: TurnBuffer):
    await _translate_event(
        {
            "type": "system",
            "subtype": "task_progress",
            "task_id": "ab3b994f72c56c517",
            "tool_use_id": "toolu_OUTER",
            "description": "Running find ...",
            "usage": {"total_tokens": 19283, "tool_uses": 1, "duration_ms": 1382},
            "last_tool_name": "Bash",
        },
        started_buf,
    )
    parsed = json.loads(started_buf._events[0])
    assert parsed["data"]["subtype"] == "task_progress"
    assert parsed["data"]["last_tool_name"] == "Bash"
    assert parsed["data"]["usage"]["duration_ms"] == 1382


async def test_translate_system_task_notification_completed(
    started_buf: TurnBuffer,
):
    await _translate_event(
        {
            "type": "system",
            "subtype": "task_notification",
            "task_id": "ab3b994f72c56c517",
            "tool_use_id": "toolu_OUTER",
            "status": "completed",
            "summary": "Count .py files in console root",
            "usage": {"total_tokens": 19508, "tool_uses": 1, "duration_ms": 2296},
        },
        started_buf,
    )
    parsed = json.loads(started_buf._events[0])
    assert parsed["data"]["subtype"] == "task_notification"
    assert parsed["data"]["status"] == "completed"


async def test_translate_system_other_subtypes_ignored(started_buf: TurnBuffer):
    """init, status, hook_started, hook_response — operational chatter that
    the chat surface doesn't need to render. Stays out of the event log."""
    for subtype in ("init", "status", "hook_started", "hook_response"):
        await _translate_event(
            {"type": "system", "subtype": subtype}, started_buf,
        )
    assert started_buf.event_count == 0


async def test_streamed_tool_call_carries_parent_tool_use_id(
    started_buf: TurnBuffer,
):
    """When a stream_event carries parent_tool_use_id (subagent inner
    tool_use that comes via streaming), the buffered tool_call must
    propagate it through content_block_start → delta → stop."""
    state: dict = {"pending_tool_uses": {}}
    await _translate_event(
        {
            "type": "stream_event",
            "parent_tool_use_id": "toolu_OUTER",
            "event": {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_INNER",
                    "name": "Bash",
                    "input": {},
                },
            },
        },
        started_buf, state,
    )
    await _translate_event(
        {
            "type": "stream_event",
            "parent_tool_use_id": "toolu_OUTER",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '{"command":"ls"}'},
            },
        },
        started_buf, state,
    )
    await _translate_event(
        {
            "type": "stream_event",
            "parent_tool_use_id": "toolu_OUTER",
            "event": {"type": "content_block_stop", "index": 0},
        },
        started_buf, state,
    )
    parsed = json.loads(started_buf._events[0])
    assert parsed["type"] == "tool_call"
    assert parsed["data"]["parent_tool_use_id"] == "toolu_OUTER"
    assert parsed["data"]["input"] == {"command": "ls"}
