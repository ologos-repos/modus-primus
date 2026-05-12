"""Provider factory. Reads [ENTERPRISE: env var] from env (or accepts an override)
and returns the matching Provider instance.

Phase 1 supports `claude-cli`. OpenAI-compatible lands in Phase 4.

When CHAT_CONSOLE_INTENT_ROUTING=true, the base provider is wrapped in an
IntentRoutingProvider that classifies each turn and dispatches "spawn-agent"
intents to agents-console (chat intents fall through to the base provider).
"""
from __future__ import annotations

import os
from typing import Optional

from .base import Provider
from .claude_cli import ClaudeCliProvider

__all__ = ["Provider", "ClaudeCliProvider", "make_provider"]


def _maybe_wrap_intent_routing(base: Provider) -> Provider:
    """Wrap `base` in IntentRoutingProvider if env opt-in is set.

    Import is lazy so installs that don't enable intent routing don't pay
    the import cost (aiohttp ClientSession setup is already paid by the
    base provider). Failure to import is logged but non-fatal: the chat
    console keeps running as plain chat.
    """
    if os.environ.get("CHAT_CONSOLE_INTENT_ROUTING", "").lower() not in (
        "1", "true", "yes", "on",
    ):
        return base
    try:
        from .intent_routing import IntentRoutingProvider
    except Exception:  # pragma: no cover — defensive
        import logging
        logging.getLogger(__name__).exception(
            "CHAT_CONSOLE_INTENT_ROUTING set but import failed; "
            "continuing with base provider"
        )
        return base
    return IntentRoutingProvider(base=base)


def make_provider(name: Optional[str] = None) -> Provider:
    """Return the configured provider. Defaults to `[ENTERPRISE: env var]` env or claude-cli."""
    name = (name or os.environ.get("[ENTERPRISE: env var]", "claude-cli")).strip()
    if name == "claude-cli":
        return _maybe_wrap_intent_routing(ClaudeCliProvider())
    raise ValueError(f"Unknown provider: {name!r}")
