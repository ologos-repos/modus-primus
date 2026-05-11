"""Tests for ClaudeCliBackend — subprocess-mocked. Verifies command
construction, stream-json translation (stream_event-wrapped + result),
end-to-end with a fake subprocess, and error paths.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from means.agents.runtime.claude_cli_backend import (
    ClaudeCliBackend,
    _translate_event,
)
from means.agents.runtime.sink import EventSink
from means.agents.runtime.store import RunStore
from means.agents.specs.model import AgentSpec


# ---------- fixtures ----------


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "agents.sqlite")


@pytest.fixture
def run_id(store: RunStore) -> str:
    run = store.create_run(
        agent_name="hello-world", spec_hash="h", fork="dev", prompt="hi",
    )
    return run.run_id


@pytest.fixture
def sink(store: RunStore, run_id: str) -> EventSink:
    return EventSink(store, run_id)


@pytest.fixture
def spec(tmp_path: Path) -> AgentSpec:
    return AgentSpec(
        name="hello-world",
        domain="research",
        fork="dev",
        model="sonnet",
        system_prompt="You are concise.",
        timeout_s=30,
        tools=[],
        qa={},
        cwd=None, requires_approval=False,
        spec_path=tmp_path / "hello-world.md",
        spec_hash="h",
    )


# ---------- command construction ----------


def test_build_cmd_includes_required_flags(spec: AgentSpec):
    cmd = ClaudeCliBackend()._build_cmd(spec, "hello prompt")
    assert cmd[0] == "claude"
    assert "--output-format" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--include-partial-messages" in cmd
    assert "--verbose" in cmd
    assert "--system-prompt" in cmd
    assert cmd[cmd.index("--system-prompt") + 1] == spec.system_prompt
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == spec.model
    assert "-p" in cmd
    assert cmd[cmd.index("-p") + 1] == "hello prompt"
    assert "--dangerously-skip-permissions" in cmd


def test_build_cmd_skip_permissions_off(spec: AgentSpec):
    cmd = ClaudeCliBackend(skip_permissions=False)._build_cmd(spec, "hi")
    assert "--dangerously-skip-permissions" not in cmd


def test_build_cmd_custom_binary_and_extra_args(spec: AgentSpec):
    backend = ClaudeCliBackend(binary="/opt/claude", extra_args=["--bare"])
    cmd = backend._build_cmd(spec, "hi")
    assert cmd[0] == "/opt/claude"
    assert "--bare" in cmd


# ---------- Phase 2: --disallowedTools enforcement ----------


def test_build_cmd_tools_explicit_empty_disallows_all(spec: AgentSpec):
    """spec.tools = [] → disallow every KNOWN_TOOL (single-shot, no agency)."""
    spec.tools = []
    cmd = ClaudeCliBackend()._build_cmd(spec, "hi")
    assert "--disallowedTools" in cmd
    deny = cmd[cmd.index("--disallowedTools") + 1]
    # Should contain every Phase-1-known tool name
    for tool in ("Read", "Edit", "Bash", "Grep", "Write"):
        assert tool in deny


def test_build_cmd_tools_populated_disallows_complement(spec: AgentSpec):
    """spec.tools = [Read, Edit] → disallow contains Bash, Grep, etc., but not Read/Edit."""
    spec.tools = ["Read", "Edit"]
    cmd = ClaudeCliBackend()._build_cmd(spec, "hi")
    deny_str = cmd[cmd.index("--disallowedTools") + 1]
    deny_set = set(deny_str.split(" "))
    assert "Read" not in deny_set
    assert "Edit" not in deny_set
    assert "Bash" in deny_set
    assert "Grep" in deny_set
    assert "Write" in deny_set


def test_build_cmd_dev_fork_default_allows_dev_tools(spec: AgentSpec):
    """spec.tools = None on dev fork → effective allowlist is dev defaults;
    deny everything else."""
    spec.tools = None  # missing → dev defaults via resolve_tools
    spec.fork = "dev"
    cmd = ClaudeCliBackend()._build_cmd(spec, "hi")
    deny_str = cmd[cmd.index("--disallowedTools") + 1]
    deny_set = set(deny_str.split(" "))
    for allowed in ("Read", "Edit", "Bash", "Grep"):
        assert allowed not in deny_set
    # Some non-default tools should be denied
    assert "Write" in deny_set
    assert "Task" in deny_set


def test_build_cmd_disallowed_uses_single_string(spec: AgentSpec):
    """We pass a single space-joined string to --disallowedTools (not multiple flags)."""
    spec.tools = ["Read"]
    cmd = ClaudeCliBackend()._build_cmd(spec, "hi")
    # Exactly one --disallowedTools occurrence
    assert cmd.count("--disallowedTools") == 1
    # The arg right after is a string with spaces (multiple tool names)
    deny = cmd[cmd.index("--disallowedTools") + 1]
    assert isinstance(deny, str)
    assert " " in deny


def test_build_cmd_tool_with_restriction_passes_through(spec: AgentSpec):
    """`Bash(git *)` allowlist entry stays in allowed (NOT in deny)."""
    spec.tools = ["Bash(git *)", "Read"]
    cmd = ClaudeCliBackend()._build_cmd(spec, "hi")
    deny = cmd[cmd.index("--disallowedTools") + 1]
    # Plain Bash IS in deny (we didn't allow unrestricted Bash, just Bash(git *))
    # The restriction syntax means claude treats them as different — `Bash` is
    # not a member of the allowlist `["Bash(git *)", "Read"]`, so it's denied.
    assert "Bash" in deny.split(" ")
    # Read is allowed → not in deny
    assert "Read" not in deny.split(" ")


# ---------- Phase 2: cwd resolution ----------


async def test_run_uses_spec_cwd_over_backend_default(
    spec: AgentSpec, store, sink, run_id, tmp_path: Path
):
    """spec.cwd takes priority over backend constructor cwd."""
    spec.cwd = str(tmp_path / "from-spec")
    (tmp_path / "from-spec").mkdir()
    backend = ClaudeCliBackend(cwd=str(tmp_path / "backend-default"))
    captured: list = []

    async def fake_exec(*args, **kwargs):
        captured.append(kwargs)
        return _FakeProcess(stdout=b"")

    from unittest.mock import AsyncMock, patch
    with patch(
        "means.agents.runtime.claude_cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=fake_exec),
    ):
        await backend.run(spec, "hi", sink)
    assert captured[0]["cwd"] == str(tmp_path / "from-spec")


async def test_run_uses_backend_cwd_when_spec_cwd_none(
    spec: AgentSpec, store, sink, run_id, tmp_path: Path
):
    """spec.cwd None → falls back to backend constructor cwd."""
    spec.cwd = None
    backend_cwd = str(tmp_path / "backend-default")
    (tmp_path / "backend-default").mkdir()
    backend = ClaudeCliBackend(cwd=backend_cwd)
    captured: list = []

    async def fake_exec(*args, **kwargs):
        captured.append(kwargs)
        return _FakeProcess(stdout=b"")

    from unittest.mock import AsyncMock, patch
    with patch(
        "means.agents.runtime.claude_cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=fake_exec),
    ):
        await backend.run(spec, "hi", sink)
    assert captured[0]["cwd"] == backend_cwd


# ---------- _translate_event (unit) ----------


class FakeSink:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, data: dict) -> int:
        self.events.append((event_type, data))
        return len(self.events) - 1


def _stream_event(inner: dict) -> dict:
    return {"type": "stream_event", "event": inner, "session_id": "X"}


def test_translate_text_delta_emits_token():
    sink = FakeSink()
    _translate_event(
        _stream_event({
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "hi"},
        }),
        sink,
    )
    assert sink.events == [("token", {"text": "hi"})]


def test_translate_text_delta_empty_skipped():
    sink = FakeSink()
    _translate_event(
        _stream_event({
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": ""},
        }),
        sink,
    )
    assert sink.events == []


def test_translate_non_text_delta_skipped():
    sink = FakeSink()
    _translate_event(
        _stream_event({
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": "{"},
        }),
        sink,
    )
    assert sink.events == []


def test_translate_message_delta_emits_running_usage():
    sink = FakeSink()
    _translate_event(
        _stream_event({
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {
                "input_tokens": 4,
                "cache_creation_input_tokens": 1500,
                "cache_read_input_tokens": 12000,
                "output_tokens": 7,
            },
        }),
        sink,
    )
    assert len(sink.events) == 1
    typ, data = sink.events[0]
    assert typ == "usage"
    assert data["total_input_tokens"] == 4 + 1500 + 12000
    assert data["output_tokens"] == 7
    assert data["final"] is False


def test_translate_result_emits_final_usage_with_cost():
    sink = FakeSink()
    _translate_event(
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
        sink,
    )
    assert len(sink.events) == 1
    typ, data = sink.events[0]
    assert typ == "usage"
    assert data["final"] is True
    assert data["total_cost_usd"] == 0.05
    assert data["total_input_tokens"] == 13504


def test_translate_unknown_events_ignored():
    sink = FakeSink()
    _translate_event({"type": "system", "subtype": "init"}, sink)
    _translate_event({"type": "rate_limit_event"}, sink)
    _translate_event({"type": "assistant"}, sink)
    _translate_event(_stream_event({"type": "message_start"}), sink)
    _translate_event(_stream_event({"type": "ping"}), sink)
    assert sink.events == []


# ---------- Phase 2: tool_call from content_block_start ----------


def test_translate_tool_call_from_content_block_start():
    sink = FakeSink()
    _translate_event(
        _stream_event({
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_01abc",
                "name": "Read",
                "input": {"file_path": "/etc/hostname"},
            },
        }),
        sink,
    )
    assert len(sink.events) == 1
    typ, data = sink.events[0]
    assert typ == "tool_call"
    assert data == {
        "id": "toolu_01abc",
        "name": "Read",
        "input": {"file_path": "/etc/hostname"},
    }


def test_translate_content_block_start_text_ignored():
    """Non-tool content blocks (plain text starts) should NOT emit tool_call."""
    sink = FakeSink()
    _translate_event(
        _stream_event({
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }),
        sink,
    )
    assert sink.events == []


def test_translate_tool_call_empty_input_passes_through():
    """Some tool invocations stream input JSON later; initial start has empty input."""
    sink = FakeSink()
    _translate_event(
        _stream_event({
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "id": "x", "name": "Bash", "input": {}},
        }),
        sink,
    )
    assert sink.events[0][1]["input"] == {}


# ---------- Phase 2: tool_result from user message ----------


def test_translate_tool_result_from_user_message():
    sink = FakeSink()
    _translate_event(
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "tool_use_id": "toolu_01abc",
                        "type": "tool_result",
                        "content": "1\thello\n2\tworld",
                    }
                ],
            },
        },
        sink,
    )
    assert len(sink.events) == 1
    typ, data = sink.events[0]
    assert typ == "tool_result"
    assert data["tool_use_id"] == "toolu_01abc"
    assert data["content"] == "1\thello\n2\tworld"
    assert data["is_error"] is False


def test_translate_tool_result_is_error_flag():
    sink = FakeSink()
    _translate_event(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "tool_use_id": "toolu_xx",
                        "type": "tool_result",
                        "content": "command failed",
                        "is_error": True,
                    }
                ],
            },
        },
        sink,
    )
    assert sink.events[0][1]["is_error"] is True


def test_translate_tool_result_content_can_be_list():
    """Some tool_results arrive as a list of content blocks (e.g. text + image).
    Pass through verbatim — the UI already handles this shape via #15's chat path."""
    sink = FakeSink()
    multipart_content = [
        {"type": "text", "text": "Here is the file:"},
        {"type": "image", "source": {"data": "..."}},
    ]
    _translate_event(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "tool_use_id": "toolu_y",
                        "type": "tool_result",
                        "content": multipart_content,
                    }
                ],
            },
        },
        sink,
    )
    assert sink.events[0][1]["content"] == multipart_content


def test_translate_user_no_tool_results_emits_nothing():
    """A user message that's plain text (no tool_result blocks) is a no-op."""
    sink = FakeSink()
    _translate_event(
        {
            "type": "user",
            "message": {
                "content": [{"type": "text", "text": "hello"}],
            },
        },
        sink,
    )
    assert sink.events == []


def test_translate_user_with_no_message_field_is_noop():
    """Defensive: top-level user with no message field shouldn't crash."""
    sink = FakeSink()
    _translate_event({"type": "user"}, sink)
    assert sink.events == []


def test_translate_user_with_string_content_is_noop():
    """Defensive: content as a string (not a list) shouldn't crash either."""
    sink = FakeSink()
    _translate_event(
        {"type": "user", "message": {"content": "just text"}},
        sink,
    )
    assert sink.events == []


# ---------- Phase 2: end-to-end with mocked tool stream ----------


async def test_run_streams_tool_call_then_result(spec, store, sink, run_id):
    """Verbatim event shapes from R1 verification: agent invokes Read; tool
    returns; agent responds with text. End-to-end events table check."""
    body = (
        # 1. tool_use start
        b'{"type":"stream_event","event":{"type":"content_block_start",'
        b'"index":1,"content_block":{"type":"tool_use","id":"toolu_01",'
        b'"name":"Read","input":{"file_path":"/etc/hostname"}}}}\n'
        # 2. tool result via user message
        b'{"type":"user","message":{"role":"user","content":'
        b'[{"tool_use_id":"toolu_01","type":"tool_result",'
        b'"content":"[ENTERPRISE: workstation hostname]","is_error":false}]}}\n'
        # 3. final text token
        b'{"type":"stream_event","event":{"type":"content_block_delta",'
        b'"delta":{"type":"text_delta","text":"[ENTERPRISE: workstation hostname]"}}}\n'
        # 4. final usage in result
        b'{"type":"result","subtype":"success","is_error":false,'
        b'"usage":{"input_tokens":3,"cache_read_input_tokens":15000,"output_tokens":8},'
        b'"total_cost_usd":0.05}\n'
    )
    fake = _FakeProcess(stdout=body)
    from unittest.mock import AsyncMock, patch
    with patch(
        "means.agents.runtime.claude_cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    ):
        await ClaudeCliBackend().run(spec, "what host is this", sink)

    events = store.get_events(run_id)
    types = [e.type for e in events]
    # status running, tool_call, tool_result, token, final usage
    assert types == ["status", "tool_call", "tool_result", "token", "usage"]
    tc = next(e for e in events if e.type == "tool_call")
    assert tc.data["name"] == "Read"
    assert tc.data["input"] == {"file_path": "/etc/hostname"}
    tr = next(e for e in events if e.type == "tool_result")
    assert tr.data["tool_use_id"] == "toolu_01"
    assert tr.data["content"] == "[ENTERPRISE: workstation hostname]"
    assert tr.data["is_error"] is False


# ---------- end-to-end with mocked subprocess ----------


class _FakeProcess:
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

    def terminate(self):
        pass


def _wrapped_token_line(text: str) -> bytes:
    return (
        b'{"type":"stream_event","event":{"type":"content_block_delta",'
        b'"delta":{"type":"text_delta","text":"' + text.encode() + b'"}}}\n'
    )


async def test_run_streams_tokens(spec, store, sink, run_id):
    body = (
        _wrapped_token_line("hello ")
        + _wrapped_token_line("world")
        + b'{"type":"result","subtype":"success","is_error":false,'
        b'"usage":{"input_tokens":3,"cache_read_input_tokens":15000,"output_tokens":2},'
        b'"total_cost_usd":0.02}\n'
    )
    fake = _FakeProcess(stdout=body)
    with patch(
        "means.agents.runtime.claude_cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    ):
        await ClaudeCliBackend().run(spec, "say hi", sink)

    events = store.get_events(run_id)
    types = [e.type for e in events]
    # status:running, then 2 tokens, then final usage
    assert types == ["status", "token", "token", "usage"]
    tokens = [e.data["text"] for e in events if e.type == "token"]
    assert tokens == ["hello ", "world"]
    usage = [e for e in events if e.type == "usage"][0]
    assert usage.data["final"] is True
    assert usage.data["total_cost_usd"] == 0.02


async def test_run_handles_split_chunks(spec, store, sink, run_id):
    """Event split across read chunks — parser must accumulate."""
    reader = asyncio.StreamReader()
    reader.feed_data(
        b'{"type":"stream_event","event":{"type":"content_block_delta",'
        b'"delta":{"type":"text_delta","text":"split'
    )
    reader.feed_data(b' message"}}}\n')
    reader.feed_eof()
    fake = _FakeProcess(stdout=b"")
    fake.stdout = reader
    with patch(
        "means.agents.runtime.claude_cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    ):
        await ClaudeCliBackend().run(spec, "p", sink)
    tokens = [e for e in store.get_events(run_id) if e.type == "token"]
    assert len(tokens) == 1
    assert tokens[0].data["text"] == "split message"


async def test_run_skips_malformed_json(spec, store, sink, run_id):
    body = (
        b"this is not json\n"
        + _wrapped_token_line("ok")
    )
    fake = _FakeProcess(stdout=body)
    with patch(
        "means.agents.runtime.claude_cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    ):
        await ClaudeCliBackend().run(spec, "p", sink)
    tokens = [e for e in store.get_events(run_id) if e.type == "token"]
    assert len(tokens) == 1


async def test_run_nonzero_exit_emits_error_and_raises(spec, store, sink, run_id):
    fake = _FakeProcess(stdout=b"", stderr=b"bad model\n", returncode=1)
    with patch(
        "means.agents.runtime.claude_cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    ):
        with pytest.raises(RuntimeError, match="exited 1"):
            await ClaudeCliBackend().run(spec, "p", sink)
    error_events = [e for e in store.get_events(run_id) if e.type == "error"]
    assert len(error_events) == 1
    assert error_events[0].data["exit_code"] == 1
    assert "bad model" in error_events[0].data["stderr"]


async def test_run_binary_missing_emits_error_and_raises(spec, store, sink, run_id):
    with patch(
        "means.agents.runtime.claude_cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=FileNotFoundError()),
    ):
        with pytest.raises(RuntimeError, match="not found"):
            await ClaudeCliBackend(binary="/nope/claude").run(spec, "p", sink)
    error_events = [e for e in store.get_events(run_id) if e.type == "error"]
    assert len(error_events) == 1
    assert "not found" in error_events[0].data["error"]


async def test_run_emits_status_running_first(spec, store, sink, run_id):
    fake = _FakeProcess(stdout=b"")
    with patch(
        "means.agents.runtime.claude_cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    ):
        await ClaudeCliBackend().run(spec, "p", sink)
    events = store.get_events(run_id)
    assert events[0].type == "status"
    assert events[0].data == {"status": "running"}


def test_backend_is_abstract():
    from means.agents.runtime.backend import AgentBackend
    with pytest.raises(TypeError):
        AgentBackend()  # type: ignore[abstract]
