"""Tests for runtime/workflow_runner.render_prompt + extract_text_output."""
from __future__ import annotations

from means.agents.runtime.store import Event
from means.agents.runtime.workflow_runner import (
    extract_text_output,
    render_prompt,
)


# ---------- render_prompt ----------


def test_substitutes_input_and_prev_output():
    out = render_prompt(
        "given {input}, transform: {prev_output}",
        input="X", prev_output="Y",
    )
    assert out == "given X, transform: Y"


def test_unknown_placeholder_passes_through():
    """Agent prompts often use their own `{file_path}`-style tokens that
    workflow rendering shouldn't mangle."""
    out = render_prompt(
        "Read {file_path} and summarize: {prev_output}",
        input="ignored", prev_output="last text",
    )
    assert out == "Read {file_path} and summarize: last text"


def test_unbalanced_braces_in_input_dont_crash():
    """Plain replacement, not str.format — unbalanced `{` survives."""
    out = render_prompt(
        "echo: {input}",
        input="raw {json: \"value\"}", prev_output="",
    )
    assert out == 'echo: raw {json: "value"}'


def test_multiline_outputs_preserved():
    out = render_prompt(
        "Polish:\n{prev_output}\nDone.",
        input="", prev_output="line one\nline two\nline three",
    )
    assert out == "Polish:\nline one\nline two\nline three\nDone."


def test_no_substitutions_leaves_template_intact():
    out = render_prompt(
        "static text only",
        input="X", prev_output="Y",
    )
    assert out == "static text only"


def test_repeated_placeholder_replaced_each_time():
    out = render_prompt(
        "{prev_output} | {prev_output}",
        input="", prev_output="HI",
    )
    assert out == "HI | HI"


# ---------- extract_text_output ----------


def _ev(seq: int, type: str, data: dict) -> Event:
    return Event(run_id="r", seq=seq, ts=0.0, type=type, data=data)


def test_concats_token_events_in_order():
    events = [
        _ev(0, "status", {"status": "running"}),
        _ev(1, "token", {"text": "Hello"}),
        _ev(2, "token", {"text": " "}),
        _ev(3, "token", {"text": "world"}),
        _ev(4, "usage", {"final": True}),
    ]
    assert extract_text_output(events) == "Hello world"


def test_skips_non_token_events():
    """tool_call / tool_result / qa_step shouldn't leak into prev_output."""
    events = [
        _ev(0, "tool_call", {"name": "Read", "input": {}}),
        _ev(1, "token", {"text": "real text"}),
        _ev(2, "tool_result", {"tool_use_id": "x", "content": "tool output"}),
        _ev(3, "qa_step", {"outcome": "pass"}),
    ]
    assert extract_text_output(events) == "real text"


def test_missing_text_field_skipped():
    """A token event without `text` (defensive) → skipped, no crash."""
    events = [
        _ev(0, "token", {}),
        _ev(1, "token", {"text": "ok"}),
    ]
    assert extract_text_output(events) == "ok"


def test_empty_events_returns_empty_string():
    assert extract_text_output([]) == ""
