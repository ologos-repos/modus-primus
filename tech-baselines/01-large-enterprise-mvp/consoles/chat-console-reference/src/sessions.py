"""Per-session state — turn count, token totals, threshold awareness.

A session is one [ENTERPRISE: cognitive engine CLI] session id (UUID). It spans multiple turns and
accumulates context. SessionRegistry holds in-memory stats for sessions the
console knows about; usage is derived from the `usage` TurnEvents the
provider appends as claude streams.

Default budget calibrated for [ENTERPRISE: cognitive engine model]'s 1M context window (chat-console#31):
nominal 800K with warn at 75% (600K) and hard at 95% (760K). Override
via CONSOLE_NOMINAL_CONTEXT / CONSOLE_SESSION_WARN_TOKENS / CONSOLE_SESSION_HARD_TOKENS.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Iterable, Optional


_DEFAULT_NOMINAL_CONTEXT = 800_000  # [ENTERPRISE: cognitive engine model] 1M window minus headroom (#31)
_DEFAULT_WARN_TOKENS = 600_000      # 75% of nominal
_DEFAULT_HARD_TOKENS = 760_000      # 95% of nominal


@dataclass
class SessionStats:
    session_id: str
    turn_count: int = 0
    last_input_tokens: int = 0       # most recent turn's prompt-cache-included input
    last_output_tokens: int = 0
    total_output_tokens: int = 0     # sum of new tokens generated across turns
    total_cost_usd: float = 0.0


@dataclass
class SessionState:
    session_id: str
    stats: SessionStats
    nominal_context: int = _DEFAULT_NOMINAL_CONTEXT
    warn_threshold: int = _DEFAULT_WARN_TOKENS
    hard_threshold: int = _DEFAULT_HARD_TOKENS

    @property
    def context_usage_ratio(self) -> float:
        """0.0 → 1.0 against the configured nominal_context. Capped at 1.0."""
        return min(self.stats.last_input_tokens / self.nominal_context, 1.0)

    @property
    def is_above_warn(self) -> bool:
        return self.stats.last_input_tokens >= self.warn_threshold

    @property
    def is_above_hard(self) -> bool:
        return self.stats.last_input_tokens >= self.hard_threshold

    @property
    def advice(self) -> Optional[str]:
        """Short string for the UI when length matters; None when fine."""
        if self.is_above_hard:
            return (
                f"Context near full ({self.stats.last_input_tokens:,} / "
                f"{self.nominal_context:,} tokens). Wrap and start a new session."
            )
        if self.is_above_warn:
            return (
                f"Context filling up ({self.stats.last_input_tokens:,} / "
                f"{self.nominal_context:,} tokens). Consider wrapping soon."
            )
        return None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "turn_count": self.stats.turn_count,
            "last_input_tokens": self.stats.last_input_tokens,
            "last_output_tokens": self.stats.last_output_tokens,
            "total_output_tokens": self.stats.total_output_tokens,
            "total_cost_usd": round(self.stats.total_cost_usd, 6),
            "nominal_context": self.nominal_context,
            "warn_threshold": self.warn_threshold,
            "hard_threshold": self.hard_threshold,
            "context_usage_ratio": round(self.context_usage_ratio, 4),
            "is_above_warn": self.is_above_warn,
            "is_above_hard": self.is_above_hard,
            "advice": self.advice,
        }


class SessionRegistry:
    """In-process map of session_id → SessionState."""

    def __init__(
        self,
        nominal_context: Optional[int] = None,
        warn_threshold: Optional[int] = None,
        hard_threshold: Optional[int] = None,
    ):
        env_nominal = int(os.environ.get("CONSOLE_NOMINAL_CONTEXT", _DEFAULT_NOMINAL_CONTEXT))
        env_warn = int(os.environ.get("CONSOLE_SESSION_WARN_TOKENS", _DEFAULT_WARN_TOKENS))
        env_hard = int(os.environ.get("CONSOLE_SESSION_HARD_TOKENS", _DEFAULT_HARD_TOKENS))
        self.nominal_context = nominal_context if nominal_context is not None else env_nominal
        self.warn_threshold = warn_threshold if warn_threshold is not None else env_warn
        self.hard_threshold = hard_threshold if hard_threshold is not None else env_hard
        self._sessions: dict[str, SessionState] = {}

    def get(self, session_id: str) -> Optional[SessionState]:
        return self._sessions.get(session_id)

    def get_or_create(self, session_id: str) -> SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            state = SessionState(
                session_id=session_id,
                stats=SessionStats(session_id=session_id),
                nominal_context=self.nominal_context,
                warn_threshold=self.warn_threshold,
                hard_threshold=self.hard_threshold,
            )
            self._sessions[session_id] = state
        return state

    def record_turn_from_events(
        self, session_id: str, raw_events: Iterable[str]
    ) -> SessionState:
        """Update stats by scanning a turn's raw JSONL events for the latest
        usage data. The provider emits `usage` events — final ones (from
        `result`) are authoritative; running ones (from `message_delta`) are
        used as fallback when the final never arrived (e.g., turn errored)."""
        state = self.get_or_create(session_id)
        latest_usage: Optional[dict] = None
        final_usage: Optional[dict] = None
        for line in raw_events:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") != "usage":
                continue
            data = ev.get("data") or {}
            latest_usage = data
            if data.get("final"):
                final_usage = data
        usage = final_usage or latest_usage
        if usage is None:
            return state
        state.stats.turn_count += 1
        state.stats.last_input_tokens = int(usage.get("total_input_tokens", 0))
        state.stats.last_output_tokens = int(usage.get("output_tokens", 0))
        state.stats.total_output_tokens += state.stats.last_output_tokens
        cost = usage.get("total_cost_usd")
        if cost is not None:
            state.stats.total_cost_usd += float(cost)
        return state
