"""Tests for runtime/usage.normalize_usage — flat shape parity across providers."""
from __future__ import annotations

from means.agents.runtime.usage import normalize_usage


def test_ollama_shape():
    out = normalize_usage(
        "ollama",
        {"prompt_eval_count": 17, "eval_count": 42},
        final=True,
    )
    assert out == {
        "input_tokens": 17,
        "output_tokens": 42,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "total_input_tokens": 17,
        "final": True,
        "provider": "ollama",
    }


def test_openai_shape():
    out = normalize_usage(
        "openai",
        {"prompt_tokens": 11, "completion_tokens": 33},
        final=True,
    )
    assert out["input_tokens"] == 11
    assert out["output_tokens"] == 33
    assert out["total_input_tokens"] == 11
    assert out["provider"] == "openai"


def test_gemini_shape():
    out = normalize_usage(
        "gemini",
        {"promptTokenCount": 9, "candidatesTokenCount": 21},
        final=True,
    )
    assert out["input_tokens"] == 9
    assert out["output_tokens"] == 21
    assert out["provider"] == "gemini"


def test_unknown_provider_zeros_out():
    """Unknown provider names don't crash — they zero the counters and
    keep the provider label so downstream display still works."""
    out = normalize_usage("madeup", {"foo": 999}, final=False)
    assert out["input_tokens"] == 0
    assert out["output_tokens"] == 0
    assert out["provider"] == "madeup"
    assert out["final"] is False


def test_missing_keys_default_to_zero():
    """Empty dict still produces valid shape — defends against partial/early
    chunks where usage fields haven't appeared yet."""
    out = normalize_usage("ollama", {}, final=False)
    assert out["input_tokens"] == 0
    assert out["output_tokens"] == 0


def test_shape_keys_match_claude_payload():
    """The flat keys (minus provider) must match _usage_payload's shape so
    the UI consumes both kinds without branching."""
    out = normalize_usage("openai", {"prompt_tokens": 1, "completion_tokens": 2}, final=True)
    expected_keys = {
        "input_tokens", "output_tokens", "cache_creation_input_tokens",
        "cache_read_input_tokens", "total_input_tokens", "final", "provider",
    }
    assert set(out) == expected_keys
