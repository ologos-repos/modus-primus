"""Judge — evaluates whether an agent run satisfies the spec's qa criteria.

LLM-as-judge: spec declares `qa: {criteria: "..."}`; after the agent run
completes, the daemon hands the run's transcript + the criteria to the
Judge, which returns pass/fail/error + a one-sentence reason. Failure
flips the run's status to `error`; pass leaves it `done`.

The judge call is HTTP-direct against an OpenAI-compatible
`/v1/chat/completions` endpoint, using `response_format: {type:
"json_schema"}` to pin the reply shape. agents-console is model-agnostic
— same wire shape works against api.openai.com, LM Studio, vLLM, etc.
Resolve order for the target URL + model:

  1. AGENTS_CONSOLE_JUDGE_URL / AGENTS_CONSOLE_JUDGE_MODEL (explicit)
  2. spec.qa.judge_model in `openai:<model-id>` form (uses
     OPENAI_BASE_URL for the URL)
  3. OPENAI_BASE_URL / OPENAI_MODEL fallback (legacy-spec compatibility)

Auth: OPENAI_API_KEY (LM-Studio-style servers accept any non-empty value).
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

from .store import Event


logger = logging.getLogger(__name__)


_DEFAULT_JUDGE_MODEL_ENV = "AGENTS_CONSOLE_JUDGE_MODEL"
_DEFAULT_JUDGE_URL_ENV = "AGENTS_CONSOLE_JUDGE_URL"
_OUTCOMES = ("pass", "fail", "error")
_TIMEOUT_SECONDS = 60.0


# OpenAI structured-output schema. `additionalProperties: false` + `strict`
# keep models from injecting trailing chatter beyond {outcome, reason}.
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
    "additionalProperties": False,
}


_SYSTEM_PROMPT = (
    "You are a strict QA judge. You read pass criteria and the transcript "
    "of an agent run, then emit a verdict object matching the provided "
    "schema: outcome ∈ {pass, fail} and a short reason. Reply with ONLY "
    "the JSON object — no prose, no markdown."
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
    """OpenAI-compatible LLM-as-judge. Verdict comes back as
    response_format=json_schema; any OpenAI-compat service that
    implements structured output works.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self._base_url_override = base_url
        self._model_override = model
        self._api_key_override = api_key

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
            base_url, model, api_key = self._resolve_target(spec)
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
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "verdict",
                    "strict": True,
                    "schema": _VERDICT_SCHEMA,
                },
            },
            "stream": False,
            "temperature": 0.0,
        }
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=_TIMEOUT_SECONDS)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=body) as resp:
                    if resp.status >= 300:
                        text = await resp.text()
                        return JudgeResult(
                            "error",
                            f"judge HTTP {resp.status}: {text[:200]}",
                        )
                    data = await resp.json()
        except Exception as exc:
            return JudgeResult("error", f"judge transport: {type(exc).__name__}: {exc}")

        content = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        ).strip()
        return _parse_verdict(content)

    def _resolve_target(self, spec: AgentSpec) -> tuple[str, str, str]:
        """Returns (base_url, model, api_key). Raises ValueError on missing
        configuration that cannot be defaulted.
        """
        # 1) Explicit overrides (constructor or env)
        env_url = self._base_url_override or os.environ.get(_DEFAULT_JUDGE_URL_ENV)
        env_model = self._model_override or os.environ.get(_DEFAULT_JUDGE_MODEL_ENV)
        if env_url and env_model:
            api_key = (
                self._api_key_override
                or os.environ.get("OPENAI_API_KEY")
                or "lm-studio"  # any non-empty value satisfies LM Studio
            )
            return env_url, env_model, api_key

        # 2) Spec-declared judge model in openai:<model-id> form (uses the
        #    operator-configured OPENAI_BASE_URL).
        judge_model = (spec.qa or {}).get("judge_model")
        if judge_model and judge_model.startswith("openai:"):
            model = judge_model[len("openai:"):]
            base = (
                self._base_url_override
                or os.environ.get("OPENAI_BASE_URL")
                or "https://api.openai.com/v1"
            )
            api_key = (
                self._api_key_override
                or os.environ.get("OPENAI_API_KEY")
                or "lm-studio"
            )
            return base, model, api_key

        # 3) Fallback to OPENAI_BASE_URL / OPENAI_MODEL.
        base = (
            self._base_url_override
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        )
        model = (
            self._model_override
            or os.environ.get("OPENAI_MODEL")
        )
        if not model:
            raise ValueError(
                "no judge model resolved — set AGENTS_CONSOLE_JUDGE_MODEL, "
                "or spec.qa.judge_model='openai:<model-id>', or OPENAI_MODEL"
            )
        api_key = (
            self._api_key_override
            or os.environ.get("OPENAI_API_KEY")
            or "lm-studio"
        )
        return base, model, api_key


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
