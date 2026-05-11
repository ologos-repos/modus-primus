"""Tests for runtime/judge — Judge ABC + LLMJudge.

Subprocess is mocked. Verdict parsing covered as a unit; end-to-end with
mocked claude exercises the full grading flow including the no-tools
denylist on the judge subprocess.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from means.agents.runtime.fork_defaults import KNOWN_TOOLS
from means.agents.runtime.judge import (
    Judge,
    JudgeResult,
    LLMJudge,
    _build_prompt,
    _format_transcript,
    _parse_verdict,
)
from means.agents.runtime.store import Event
from means.agents.specs.model import AgentSpec


# ---------- JudgeResult ----------


def test_judge_result_validates_outcome():
    JudgeResult("pass", "ok")
    JudgeResult("fail", "x")
    JudgeResult("error", "y")
    with pytest.raises(ValueError, match="outcome"):
        JudgeResult("maybe", "??")


def test_judge_is_abstract():
    with pytest.raises(TypeError):
        Judge()  # type: ignore[abstract]


# ---------- _parse_verdict ----------


def test_parse_pass():
    r = _parse_verdict("PASS: looks good")
    assert r.outcome == "pass"
    assert r.reason == "looks good"


def test_parse_fail():
    r = _parse_verdict("FAIL: too verbose")
    assert r.outcome == "fail"
    assert r.reason == "too verbose"


def test_parse_pass_only_first_line():
    """Multi-line response: take the first line; ignore trailing prose."""
    r = _parse_verdict("PASS: ok\n\nAdditional thoughts the judge had...")
    assert r.outcome == "pass"
    assert r.reason == "ok"


def test_parse_case_insensitive_prefix():
    r = _parse_verdict("pass: lowercase prefix accepted")
    assert r.outcome == "pass"


def test_parse_unparseable_is_error():
    r = _parse_verdict("Yeah I think it's fine")
    assert r.outcome == "error"
    assert "unparseable" in r.reason


def test_parse_empty_is_error():
    r = _parse_verdict("")
    assert r.outcome == "error"


def test_parse_pass_no_reason():
    """`PASS:` alone → outcome pass, default reason."""
    r = _parse_verdict("PASS:")
    assert r.outcome == "pass"
    assert r.reason == "ok"


def test_parse_fail_no_reason():
    r = _parse_verdict("FAIL:")
    assert r.outcome == "fail"
    assert r.reason == "criteria not met"


# ---------- _format_transcript ----------


def _ev(typ: str, data: dict, seq: int = 0) -> Event:
    return Event(run_id="r", seq=seq, ts=0.0, type=typ, data=data)


def test_format_transcript_concatenates_tokens_into_response():
    events = [
        _ev("status", {"status": "running"}, 0),
        _ev("token", {"text": "hello"}, 1),
        _ev("token", {"text": " world"}, 2),
    ]
    text = _format_transcript(events)
    assert "[response] hello world" in text


def test_format_transcript_renders_tool_calls_and_results():
    events = [
        _ev("tool_call", {"name": "Read", "input": {"file_path": "/etc/hostname"}}, 0),
        _ev("tool_result", {"tool_use_id": "x", "content": "[ENTERPRISE: workstation hostname]", "is_error": False}, 1),
        _ev("token", {"text": "host: [ENTERPRISE: org identifier]"}, 2),
    ]
    text = _format_transcript(events)
    assert "[tool_call] Read" in text
    assert "/etc/hostname" in text
    assert "[tool_result]" in text
    assert "[ENTERPRISE: workstation hostname]" in text
    assert "[response] host: [ENTERPRISE: org identifier]" in text


def test_format_transcript_marks_error_results():
    events = [
        _ev("tool_call", {"name": "Bash", "input": {"command": "false"}}),
        _ev("tool_result", {"content": "exit 1", "is_error": True}, 1),
    ]
    text = _format_transcript(events)
    assert "(ERROR)" in text


def test_format_transcript_empty():
    assert _format_transcript([]) == "(empty transcript)"


def test_format_transcript_handles_list_content():
    """tool_result.content may be a list of blocks; render as JSON."""
    events = [
        _ev("tool_call", {"name": "Read", "input": {}}, 0),
        _ev("tool_result", {"content": [{"type": "text", "text": "hi"}]}, 1),
    ]
    text = _format_transcript(events)
    assert "type" in text  # the JSON-rendered list


# ---------- _build_prompt ----------


def test_build_prompt_contains_all_inputs():
    p = _build_prompt(
        criteria="Output must be under 50 words.",
        original_prompt="Summarize this file.",
        transcript="[response] foo bar",
    )
    assert "Output must be under 50 words" in p
    assert "Summarize this file" in p
    assert "[response] foo bar" in p
    assert "Verdict" in p


# ---------- LLMJudge (subprocess mocked) ----------


def _spec(criteria: str | None = None, judge_model: str | None = None) -> AgentSpec:
    qa = {}
    if criteria is not None:
        qa["criteria"] = criteria
    if judge_model is not None:
        qa["judge_model"] = judge_model
    return AgentSpec(
        name="x", domain="", fork="dev",
        model="sonnet", system_prompt="",
        timeout_s=60, tools=[], qa=qa, cwd=None, requires_approval=False,
        spec_path=Path("/x.md"), spec_hash="h",
    )


class _FakeProc:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr


async def test_llmjudge_no_criteria_passes_vacuously():
    spec = _spec(criteria=None)
    result = await LLMJudge().judge(spec, "prompt", [])
    assert result.outcome == "pass"
    assert "no qa criteria" in result.reason


async def test_llmjudge_pass_verdict():
    spec = _spec(criteria="Reply must be concise.")
    fake = _FakeProc(stdout=b"PASS: under 50 words\n")
    with patch(
        "means.agents.runtime.judge.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    ):
        result = await LLMJudge().judge(spec, "p", [])
    assert result.outcome == "pass"
    assert result.reason == "under 50 words"


async def test_llmjudge_fail_verdict():
    spec = _spec(criteria="Must contain the word 'banana'.")
    fake = _FakeProc(stdout=b"FAIL: missing banana\n")
    with patch(
        "means.agents.runtime.judge.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    ):
        result = await LLMJudge().judge(spec, "p", [])
    assert result.outcome == "fail"
    assert result.reason == "missing banana"


async def test_llmjudge_subprocess_failure_is_error():
    spec = _spec(criteria="x")
    fake = _FakeProc(stdout=b"", stderr=b"out of credits\n", returncode=1)
    with patch(
        "means.agents.runtime.judge.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    ):
        result = await LLMJudge().judge(spec, "p", [])
    assert result.outcome == "error"
    assert "exited 1" in result.reason
    assert "out of credits" in result.reason


async def test_llmjudge_binary_missing_is_error():
    spec = _spec(criteria="x")
    with patch(
        "means.agents.runtime.judge.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=FileNotFoundError()),
    ):
        result = await LLMJudge(binary="/nope/claude").judge(spec, "p", [])
    assert result.outcome == "error"
    assert "not found" in result.reason


async def test_llmjudge_passes_disallowed_tools():
    """Judge subprocess must run with EVERY KNOWN_TOOL denied — judge can't side-effect."""
    spec = _spec(criteria="x")
    fake = _FakeProc(stdout=b"PASS: ok\n")
    captured: list[list[str]] = []

    async def grab(*args, **kwargs):
        captured.append(list(args))
        return fake

    with patch(
        "means.agents.runtime.judge.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=grab),
    ):
        await LLMJudge().judge(spec, "p", [])
    cmd = captured[0]
    assert "--disallowedTools" in cmd
    deny = cmd[cmd.index("--disallowedTools") + 1].split(" ")
    for tool in ("Read", "Edit", "Bash", "Grep", "Write"):
        assert tool in deny
    # Judge always uses --dangerously-skip-permissions (we already deny everything)
    assert "--dangerously-skip-permissions" in cmd


async def test_llmjudge_uses_default_model():
    spec = _spec(criteria="x")
    fake = _FakeProc(stdout=b"PASS: ok\n")
    captured: list[list[str]] = []

    async def grab(*args, **kwargs):
        captured.append(list(args))
        return fake

    with patch(
        "means.agents.runtime.judge.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=grab),
    ):
        await LLMJudge(default_model="haiku").judge(spec, "p", [])
    cmd = captured[0]
    assert cmd[cmd.index("--model") + 1] == "haiku"


async def test_llmjudge_spec_judge_model_overrides_default():
    spec = _spec(criteria="x", judge_model="opus")
    fake = _FakeProc(stdout=b"PASS: ok\n")
    captured: list[list[str]] = []

    async def grab(*args, **kwargs):
        captured.append(list(args))
        return fake

    with patch(
        "means.agents.runtime.judge.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=grab),
    ):
        await LLMJudge(default_model="sonnet").judge(spec, "p", [])
    cmd = captured[0]
    assert cmd[cmd.index("--model") + 1] == "opus"


async def test_llmjudge_unparseable_response_is_error():
    spec = _spec(criteria="x")
    fake = _FakeProc(stdout=b"I don't know really, maybe pass.\n")
    with patch(
        "means.agents.runtime.judge.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    ):
        result = await LLMJudge().judge(spec, "p", [])
    assert result.outcome == "error"
    assert "unparseable" in result.reason
