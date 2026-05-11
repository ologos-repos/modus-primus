"""normalize_usage — flatten provider-specific usage blocks into the UI shape.

Each provider names token counts differently (Ollama uses prompt_eval_count,
OpenAI uses prompt_tokens, Gemini uses promptTokenCount), so the agents UI
would need a switch statement per provider if we surfaced raw shapes. This
helper pre-flattens to the same dict shape that ClaudeCliBackend's
`_usage_payload` produces, with cache_* zeroed for non-claude providers
(none of them expose prompt-cache concepts as of 2026-05). The `provider`
key is added so downstream code can still tell them apart when needed.
"""
from __future__ import annotations


def normalize_usage(provider: str, raw: dict, *, final: bool) -> dict:
    """Build a flat usage event payload for `sink.emit("usage", ...)`."""
    input_tokens, output_tokens = _extract(provider, raw)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        # Non-claude providers don't expose prompt-cache; zero these so the
        # UI's total_input_tokens math (input + cache_creation + cache_read)
        # stays correct.
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "total_input_tokens": input_tokens,
        "final": final,
        "provider": provider,
    }


def _extract(provider: str, raw: dict) -> tuple[int, int]:
    if provider == "ollama":
        return (
            int(raw.get("prompt_eval_count", 0) or 0),
            int(raw.get("eval_count", 0) or 0),
        )
    if provider == "openai":
        return (
            int(raw.get("prompt_tokens", 0) or 0),
            int(raw.get("completion_tokens", 0) or 0),
        )
    if provider == "gemini":
        return (
            int(raw.get("promptTokenCount", 0) or 0),
            int(raw.get("candidatesTokenCount", 0) or 0),
        )
    return (0, 0)
