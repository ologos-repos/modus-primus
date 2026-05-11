"""AgentBackend ABC.

A backend is the "how the model gets invoked" layer — single-shot HTTPS to
[ENTERPRISE: cognitive engine vendor], OpenAI, Gemini, Ollama, etc. Phase 1 ships a single concrete
implementation (AnthropicBackend, single-shot text-only).

Backends emit events to an `EventSink`; they don't touch storage or chat
notification directly. That separation keeps each backend small and
testable in isolation (mock the sink, verify event ordering).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..specs.model import AgentSpec

from .sink import EventSink


class AgentBackend(ABC):
    """Pluggable model-invocation strategy."""

    @abstractmethod
    async def run(
        self, spec: AgentSpec, prompt: str, sink: EventSink
    ) -> None:
        """Drive a single run from prompt to completion.

        Emits events to `sink` (token / usage / status / error). On success,
        returns normally. On failure, emits an `error` event before raising
        so the caller (daemon) can persist the failure cleanly.
        """
        ...
