"""Provider factory. Reads [ENTERPRISE: env var] from env (or accepts an override)
and returns the matching Provider instance.

Phase 1 supports `claude-cli`. OpenAI-compatible lands in Phase 4.
"""
from __future__ import annotations

import os
from typing import Optional

from .base import Provider
from .claude_cli import ClaudeCliProvider

__all__ = ["Provider", "ClaudeCliProvider", "make_provider"]


def make_provider(name: Optional[str] = None) -> Provider:
    """Return the configured provider. Defaults to `[ENTERPRISE: env var]` env or claude-cli."""
    name = (name or os.environ.get("[ENTERPRISE: env var]", "claude-cli")).strip()
    if name == "claude-cli":
        return ClaudeCliProvider()
    raise ValueError(f"Unknown provider: {name!r}")
