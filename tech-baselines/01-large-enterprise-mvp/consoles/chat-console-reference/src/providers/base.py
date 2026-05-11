"""Provider interface. A Provider drives one turn from prompt to completion,
calling buf.start(), appending TurnEvents, and finishing the buffer.

Concrete implementations: ClaudeCliProvider (Phase 1),
OpenAiCompatibleProvider (Phase 4).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from turns import TurnBuffer


class Provider(ABC):
    """Abstract LLM provider — translates model output stream into TurnBuffer events."""

    @abstractmethod
    async def __call__(
        self,
        buf: TurnBuffer,
        prompt: str,
        *,
        session_id: str,
        is_new_session: bool,
    ) -> None:
        """Run a turn through to completion.

        - `session_id` — the conversation's identity (UUID). Same id used in
          terminal `claude --resume <id>` invocations gives shared memory.
        - `is_new_session` — true for the first turn of a conversation
          (provider creates the session); false for subsequent turns
          (provider resumes).
        """
        ...
