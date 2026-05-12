"""Tests for runtime/judge — Judge ABC + LLMJudge (Ollama-HTTP-backed).

Network is mocked. _parse_verdict covers the new constrained-JSON shape;
LLMJudge tests verify the resolve_target precedence and the
JSON-decode/HTTP-error fallbacks.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from means.agents.runtime.judge import (
    Judge,
    JudgeResult,
    LLMJudge,
    _build_user_message,
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


# ---------- _parse_verdict (constrained JSON) ----------


def test_parse_pass_json():
    r = _parse_verdict('{"outcome": "pass", "reason": "looks good"}')
    assert r.outcome == "pass"
    assert r.reason == "looks good"


def test_parse_fail_json():
    r = _parse_verdict('{"outcome": "fail", "reason": "too verbose"}')
    assert r.outcome == "fail"
    assert r.reason == "too verbose"


def test_parse_unknown_outcome_is_error():
    r = _parse_verdict('{"outcome": "maybe", "reason": "unsure"}')
    assert r.outcome == "error"
    assert "maybe" in r.reason


def test_parse_missing_outcome_is_error():
    r = _parse_verdict('{"reason": "no outcome given"}')
    assert r.outcome == "error"


def test_parse_empty_is_error():
    r = _parse_verdict("")
    assert r.outcome == "error"


def test_parse_garbage_is_error():
    r = _parse_verdict("Sure, the agent did well I think.")
    assert r.outcome == "error"


def test_parse_recovers_from_markdown_wrapping():
    """Some models wrap JSON in ```json fences even with format=schema."""
    r = _parse_verdict(
        '```json\n{"outcome": "pass", "reason": "ok"}\n```'
    )
    assert r.outcome == "pass"


def test_parse_caps_reason_length():
    long = "x" * 500
    r = _parse_verdict(f'{{"outcome": "pass", "reason": "{long}"}}')
    assert r.outcome == "pass"
    assert len(r.reason) <= 300


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
        _ev("tool_result", {"content": "host", "is_error": False}, 1),
    ]
    text = _format_transcript(events)
    assert "[tool_call] Read" in text
    assert "[tool_result] host" in text


def test_format_transcript_empty():
    assert _format_transcript([]) == "(empty transcript)"


# ---------- _build_user_message ----------


def test_build_user_message_contains_all_inputs():
    p = _build_user_message(
        criteria="Output must be under 50 words.",
        original_prompt="Summarize this file.",
        transcript="[response] foo bar",
    )
    assert "Output must be under 50 words" in p
    assert "Summarize this file" in p
    assert "[response] foo bar" in p


# ---------- LLMJudge (aiohttp mocked) ----------


def _spec(criteria: str | None = None, judge_model: str | None = None) -> AgentSpec:
    qa = {}
    if criteria is not None:
        qa["criteria"] = criteria
    if judge_model is not None:
        qa["judge_model"] = judge_model
    return AgentSpec(
        name="x", domain="", fork="dev",
        model="ollama:tracys-mac/gemma3:12b", system_prompt="",
        timeout_s=60, tools=[], qa=qa, cwd=None, requires_approval=False,
        spec_path=Path("/x.md"), spec_hash="h",
    )


def _mock_chat_response(payload_content: str, status: int = 200):
    """Build a context-manager mock that yields the canned /api/chat reply."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value={"message": {"content": payload_content}})
    resp.text = AsyncMock(return_value=payload_content)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _mock_session(post_cm):
    sess = MagicMock()
    sess.post = MagicMock(return_value=post_cm)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=sess)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


async def test_llmjudge_no_criteria_passes_vacuously(monkeypatch):
    monkeypatch.setenv("AGENTS_CONSOLE_JUDGE_URL", "http://example:11434")
    monkeypatch.setenv("AGENTS_CONSOLE_JUDGE_MODEL", "gemma3:12b")
    spec = _spec(criteria=None)
    result = await LLMJudge().judge(spec, "prompt", [])
    assert result.outcome == "pass"
    assert "no qa criteria" in result.reason


async def test_llmjudge_pass_verdict(monkeypatch):
    monkeypatch.setenv("AGENTS_CONSOLE_JUDGE_URL", "http://example:11434")
    monkeypatch.setenv("AGENTS_CONSOLE_JUDGE_MODEL", "gemma3:12b")
    spec = _spec(criteria="Reply must be concise.")
    post_cm = _mock_chat_response(
        '{"outcome": "pass", "reason": "under 50 words"}'
    )
    with patch(
        "means.agents.runtime.judge.aiohttp.ClientSession",
        return_value=_mock_session(post_cm),
    ):
        result = await LLMJudge().judge(spec, "p", [])
    assert result.outcome == "pass"
    assert "under 50 words" in result.reason


async def test_llmjudge_fail_verdict(monkeypatch):
    monkeypatch.setenv("AGENTS_CONSOLE_JUDGE_URL", "http://example:11434")
    monkeypatch.setenv("AGENTS_CONSOLE_JUDGE_MODEL", "gemma3:12b")
    spec = _spec(criteria="Must contain the word 'banana'.")
    post_cm = _mock_chat_response(
        '{"outcome": "fail", "reason": "missing banana"}'
    )
    with patch(
        "means.agents.runtime.judge.aiohttp.ClientSession",
        return_value=_mock_session(post_cm),
    ):
        result = await LLMJudge().judge(spec, "p", [])
    assert result.outcome == "fail"
    assert "missing banana" in result.reason


async def test_llmjudge_http_500_is_error(monkeypatch):
    monkeypatch.setenv("AGENTS_CONSOLE_JUDGE_URL", "http://example:11434")
    monkeypatch.setenv("AGENTS_CONSOLE_JUDGE_MODEL", "gemma3:12b")
    spec = _spec(criteria="x")
    post_cm = _mock_chat_response("model loading…", status=500)
    with patch(
        "means.agents.runtime.judge.aiohttp.ClientSession",
        return_value=_mock_session(post_cm),
    ):
        result = await LLMJudge().judge(spec, "p", [])
    assert result.outcome == "error"
    assert "HTTP 500" in result.reason


async def test_llmjudge_unparseable_response_is_error(monkeypatch):
    monkeypatch.setenv("AGENTS_CONSOLE_JUDGE_URL", "http://example:11434")
    monkeypatch.setenv("AGENTS_CONSOLE_JUDGE_MODEL", "gemma3:12b")
    spec = _spec(criteria="x")
    post_cm = _mock_chat_response("I think it's fine, no JSON here.")
    with patch(
        "means.agents.runtime.judge.aiohttp.ClientSession",
        return_value=_mock_session(post_cm),
    ):
        result = await LLMJudge().judge(spec, "p", [])
    assert result.outcome == "error"


async def test_llmjudge_missing_config_is_error(monkeypatch):
    """No env, no judge_model, no OLLAMA_MODEL → clean ValueError surfaces."""
    for var in (
        "AGENTS_CONSOLE_JUDGE_URL", "AGENTS_CONSOLE_JUDGE_MODEL",
        "OLLAMA_URL", "OLLAMA_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    spec = _spec(criteria="x")  # judge_model not set
    result = await LLMJudge().judge(spec, "p", [])
    assert result.outcome == "error"
    assert "no judge model" in result.reason
