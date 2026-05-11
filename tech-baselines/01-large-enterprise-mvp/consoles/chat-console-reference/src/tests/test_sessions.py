"""Tests for sessions.py — per-session state, threshold logic, usage extraction."""
import json

import pytest

from sessions import SessionRegistry, SessionState, SessionStats


def _usage_event(
    *,
    final: bool,
    input_tokens: int = 0,
    cache_creation: int = 0,
    cache_read: int = 0,
    output_tokens: int = 0,
    cost: float | None = None,
) -> str:
    payload = {
        "input_tokens": input_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "output_tokens": output_tokens,
        "total_input_tokens": input_tokens + cache_creation + cache_read,
        "final": final,
    }
    if cost is not None:
        payload["total_cost_usd"] = cost
    return json.dumps({"type": "usage", "data": payload}, separators=(",", ":"))


def test_get_or_create_returns_same_instance():
    reg = SessionRegistry()
    s1 = reg.get_or_create("X")
    s2 = reg.get_or_create("X")
    assert s1 is s2


def test_get_returns_none_for_unknown():
    reg = SessionRegistry()
    assert reg.get("nope") is None


def test_record_turn_uses_final_usage_when_present():
    reg = SessionRegistry()
    events = [
        _usage_event(final=False, input_tokens=4, cache_read=10000, output_tokens=1),
        _usage_event(final=False, input_tokens=4, cache_read=10000, output_tokens=5),
        _usage_event(
            final=True,
            input_tokens=4,
            cache_creation=2000,
            cache_read=10000,
            output_tokens=12,
            cost=0.05,
        ),
    ]
    state = reg.record_turn_from_events("X", events)
    assert state.stats.turn_count == 1
    assert state.stats.last_input_tokens == 4 + 2000 + 10000  # total_input_tokens
    assert state.stats.last_output_tokens == 12
    assert state.stats.total_output_tokens == 12
    assert state.stats.total_cost_usd == pytest.approx(0.05)


def test_record_turn_falls_back_to_running_usage_when_no_final():
    """If a turn errored before the result event, use the latest message_delta usage."""
    reg = SessionRegistry()
    events = [
        _usage_event(final=False, input_tokens=4, cache_read=5000, output_tokens=3),
    ]
    state = reg.record_turn_from_events("X", events)
    assert state.stats.turn_count == 1
    assert state.stats.last_input_tokens == 5004
    assert state.stats.last_output_tokens == 3


def test_record_turn_no_usage_events_does_not_increment():
    reg = SessionRegistry()
    state = reg.record_turn_from_events(
        "X", [json.dumps({"type": "token", "data": {"text": "hi"}})]
    )
    assert state.stats.turn_count == 0


def test_record_turn_skips_malformed_lines():
    reg = SessionRegistry()
    events = [
        "not json",
        _usage_event(final=True, cache_read=100, output_tokens=5),
    ]
    state = reg.record_turn_from_events("X", events)
    assert state.stats.turn_count == 1
    assert state.stats.last_input_tokens == 100


def test_record_turn_accumulates_across_turns():
    reg = SessionRegistry()
    reg.record_turn_from_events(
        "X", [_usage_event(final=True, cache_read=1000, output_tokens=10, cost=0.01)]
    )
    reg.record_turn_from_events(
        "X", [_usage_event(final=True, cache_read=2000, output_tokens=20, cost=0.02)]
    )
    state = reg.get("X")
    assert state.stats.turn_count == 2
    assert state.stats.last_input_tokens == 2000  # the *last* turn's
    assert state.stats.total_output_tokens == 30
    assert state.stats.total_cost_usd == pytest.approx(0.03)


def test_threshold_warn():
    reg = SessionRegistry(warn_threshold=100, hard_threshold=200)
    reg.record_turn_from_events("X", [_usage_event(final=True, cache_read=120)])
    state = reg.get("X")
    assert state.is_above_warn is True
    assert state.is_above_hard is False
    assert state.advice is not None
    assert "filling up" in state.advice.lower()


def test_threshold_hard():
    reg = SessionRegistry(warn_threshold=100, hard_threshold=200)
    reg.record_turn_from_events("X", [_usage_event(final=True, cache_read=210)])
    state = reg.get("X")
    assert state.is_above_warn is True
    assert state.is_above_hard is True
    assert state.advice is not None
    assert "near full" in state.advice.lower()


def test_no_advice_below_warn():
    reg = SessionRegistry(warn_threshold=100, hard_threshold=200)
    reg.record_turn_from_events("X", [_usage_event(final=True, cache_read=50)])
    state = reg.get("X")
    assert state.is_above_warn is False
    assert state.advice is None


def test_context_usage_ratio_capped_at_one():
    """chat-console#31: nominal default is 800K; ratio caps at 1.0."""
    reg = SessionRegistry()
    reg.record_turn_from_events("X", [_usage_event(final=True, cache_read=1_200_000)])
    state = reg.get("X")
    assert state.context_usage_ratio == 1.0


def test_context_usage_ratio_uses_nominal_context():
    """chat-console#31: ratio divides by nominal_context, not a hardcoded literal."""
    reg = SessionRegistry(nominal_context=1000)
    reg.record_turn_from_events("X", [_usage_event(final=True, cache_read=250)])
    state = reg.get("X")
    assert abs(state.context_usage_ratio - 0.25) < 1e-6


def test_to_dict_shape():
    reg = SessionRegistry(warn_threshold=10, hard_threshold=20)
    reg.record_turn_from_events("X", [_usage_event(final=True, cache_read=15, output_tokens=2)])
    d = reg.get("X").to_dict()
    expected_keys = {
        "session_id", "turn_count", "last_input_tokens", "last_output_tokens",
        "total_output_tokens", "total_cost_usd",
        "nominal_context", "warn_threshold", "hard_threshold",
        "context_usage_ratio", "is_above_warn", "is_above_hard", "advice",
    }
    assert set(d.keys()) == expected_keys


def test_nominal_context_from_env(monkeypatch):
    """chat-console#31: CONSOLE_NOMINAL_CONTEXT env var overrides the default."""
    monkeypatch.setenv("CONSOLE_NOMINAL_CONTEXT", "100000")
    reg = SessionRegistry()
    assert reg.nominal_context == 100000


def test_default_nominal_context_is_800k():
    """chat-console#31: bumped from 200K to 800K as the default."""
    reg = SessionRegistry()
    assert reg.nominal_context == 800_000
    assert reg.warn_threshold == 600_000
    assert reg.hard_threshold == 760_000


def test_thresholds_from_env(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_WARN_TOKENS", "1234")
    monkeypatch.setenv("CONSOLE_SESSION_HARD_TOKENS", "5678")
    reg = SessionRegistry()
    assert reg.warn_threshold == 1234
    assert reg.hard_threshold == 5678
