"""Judge — evaluates whether an agent run satisfies the spec's qa criteria.

LLM-as-judge: spec declares `qa: {criteria: "..."}`; after the agent run
completes, the daemon hands the run's transcript + the criteria to the
Judge, which returns pass/fail/error + a one-sentence reason. Failure
flips the run's status to `error`; pass leaves it `done`.

The judge call is HTTP-direct against an Ollama-compatible /api/chat
endpoint. agents-console is model-agnostic — there's no longer a
subprocess CLI dependency. Judge target URL + model resolve in order:

  1. AGENTS_CONSOLE_JUDGE_URL / AGENTS_CONSOLE_JUDGE_MODEL (explicit)
  2. ollama_hosts.json + spec.qa.judge_model (when judge_model carries
     an `ollama:<host-alias>/<model-tag>` shape)
  3. OLLAMA_URL / OLLAMA_MODEL (fallback to the same defaults the
     OllamaBackend uses)

Format-constrained JSON (Ollama `format` parameter) pins the response
into {outcome, reason} so any Ollama-served model works regardless of
native tool support.
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import aiohttp

from ..specs.model import AgentSpec

from .ollama_hosts import load_hosts
from .store import Event


logger = logging.getLogger(__name__)


_DEFAULT_JUDGE_MODEL_ENV = "AGENTS_CONSOLE_JUDGE_MODEL"
_DEFAULT_JUDGE_URL_ENV = "AGENTS_CONSOLE_JUDGE_URL"
_OUTCOMES = ("pass", "fail", "error")
_TIMEOUT_SECONDS = 60.0


# JSON schema passed to Ollama's `format` parameter — pins the reply shape.
_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {
            "type": "string",
            "enum": ["pass", "fail"],
        },
        "reason": {
            "type": "string",
            "description": "one short sentence",
        },
    },
    "required": ["outcome", "reason"],
}


_SYSTEM_PROMPT = (
    "You are a strict QA judge. You read pass criteria and the transcript "
    "of an agent run, then emit a verdict object: "
    "{\"outcome\": \"pass\"|\"fail\", \"reason\": \"<one short sentence>\"}. "
    "Reply with ONLY the JSON object — no prose, no markdown."
)


@dataclass
class JudgeResult:
    outcome: str  # 'pass' | 'fail' | 'error'
    reason: str

    def __post_init__(self):
        if self.outcome not in _OUTCOMES:
            raise ValueError(f"outcome must be one of {_OUTCOMES}, got {self.outcome!r}")


class Judge(ABC):
    """Pluggable verdict-emitter."""

    @abstractmethod
    async def judge(
        self,
        spec: AgentSpec,
        prompt: str,
        events: list[Event],
    ) -> JudgeResult:
        ...


class LLMJudge(Judge):
    """Ollama-backed LLM-as-judge. Verdict comes back as format-constrained
    JSON; any Ollama-served model works.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self._base_url_override = base_url
        self._model_override = model

    async def judge(
        self,
        spec: AgentSpec,
        prompt: str,
        events: list[Event],
    ) -> JudgeResult:
        criteria = (spec.qa or {}).get("criteria")
        if not criteria:
            return JudgeResult("pass", "no qa criteria")

        try:
            base_url, model = self._resolve_target(spec)
        except ValueError as e:
            return JudgeResult("error", f"judge config: {e}")

        transcript = _format_transcript(events)
        user_msg = _build_user_message(criteria, prompt, transcript)
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "format": _VERDICT_SCHEMA,
            "stream": False,
            "options": {"temperature": 0.0},
        }
        url = f"{base_url.rstrip('/')}/api/chat"
        timeout = aiohttp.ClientTimeout(total=_TIMEOUT_SECONDS)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body) as resp:
                    if resp.status >= 300:
                        text = await resp.text()
                        return JudgeResult(
                            "error",
                            f"judge HTTP {resp.status}: {text[:200]}",
                        )
                    data = await resp.json()
        except Exception as exc:
            return JudgeResult("error", f"judge transport: {type(exc).__name__}: {exc}")

        content = ((data.get("message") or {}).get("content") or "").strip()
        return _parse_verdict(content)

    def _resolve_target(self, spec: AgentSpec) -> tuple[str, str]:
        """Returns (base_url, model). Raises ValueError on missing config."""
        # 1) Explicit overrides (constructor or env)
        if self._base_url_override and self._model_override:
            return self._base_url_override, self._model_override
        env_url = os.environ.get(_DEFAULT_JUDGE_URL_ENV)
        env_model = os.environ.get(_DEFAULT_JUDGE_MODEL_ENV)
        if env_url and env_model:
            return env_url, env_model

        # 2) Spec-declared judge model in ollama:<alias>/<tag> form
        judge_model = (spec.qa or {}).get("judge_model")
        if judge_model and judge_model.startswith("ollama:"):
            tag = judge_model[len("ollama:"):]
            host_alias, sep, model_tag = tag.partition("/")
            if sep and model_tag:
                hosts = load_hosts()
                if host_alias in hosts:
                    return hosts[host_alias], model_tag

        # 3) Fallback to OLLAMA_URL/MODEL (same defaults as OllamaBackend
        #    when no host alias is in scope).
        base = self._base_url_override or os.environ.get(
            "OLLAMA_URL", "http://127.0.0.1:11434"
        )
        mdl = self._model_override or os.environ.get("OLLAMA_MODEL")
        if not mdl:
            raise ValueError(
                "no judge model resolved — set AGENTS_CONSOLE_JUDGE_MODEL, "
                "or spec.qa.judge_model='ollama:<alias>/<tag>', "
                "or OLLAMA_MODEL"
            )
        return base, mdl


def _format_transcript(events: list[Event]) -> str:
    """Compact, human-readable rendering of the run's events for the judge."""
    lines: list[str] = []
    response_buf: list[str] = []
    for ev in events:
        if ev.type == "token":
            response_buf.append(ev.data.get("text", ""))
        else:
            if response_buf:
                lines.append(f"[response] {''.join(response_buf)}")
                response_buf = []
            if ev.type == "tool_call":
                name = ev.data.get("name", "?")
                inp = ev.data.get("input", {})
                lines.append(f"[tool_call] {name} input={json.dumps(inp, separators=(',', ':'))}")
            elif ev.type == "tool_result":
                content = ev.data.get("content")
                if isinstance(content, list):
                    content = json.dumps(content, separators=(",", ":"))
                err_marker = " (ERROR)" if ev.data.get("is_error") else ""
                lines.append(f"[tool_result]{err_marker} {str(content)[:1000]}")
            elif ev.type == "error":
                lines.append(f"[error] {ev.data}")
    if response_buf:
        lines.append(f"[response] {''.join(response_buf)}")
    return "\n".join(lines) or "(empty transcript)"


def _build_user_message(criteria: str, original_prompt: str, transcript: str) -> str:
    return (
        f"Pass criteria: {criteria}\n\n"
        f"Original user prompt: {original_prompt}\n\n"
        f"Agent transcript:\n{transcript}\n\n"
        "Return your verdict JSON."
    )


def _parse_verdict(text: str) -> JudgeResult:
    """Parse the constrained-JSON verdict."""
    if not text:
        return JudgeResult("error", "judge returned empty output")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return JudgeResult(
                    "error", f"judge response not JSON: {text[:200]}"
                )
        else:
            return JudgeResult(
                "error", f"judge response had no JSON object: {text[:200]}"
            )
    outcome = (parsed.get("outcome") or "").strip().lower()
    reason = (parsed.get("reason") or "").strip()[:300] or "no reason given"
    if outcome not in ("pass", "fail"):
        return JudgeResult("error", f"judge outcome={outcome!r} not pass/fail")
    return JudgeResult(outcome, reason)
