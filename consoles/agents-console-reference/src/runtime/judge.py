"""Judge — evaluates whether an agent run satisfies the spec's qa criteria.

Phase 3: LLM-as-judge only. Spec declares `qa: {criteria: "..."}`; after
the agent run completes, the daemon hands the run's transcript + the
criteria to the Judge, which returns pass/fail/error + a one-sentence
reason. Failure flips the run's status to `error`; pass leaves it `done`.

Uses `claude -p` for the grading itself (subscription-auth, no API key).
The judge agent gets NO tools (KNOWN_TOOLS as denylist) so it can't
side-effect — purely reads the transcript and emits a verdict line.

The cost shape is one extra claude call per QA-enabled run. JD's spec
can override `qa.judge_model` to use a cheaper model (e.g. `haiku`)
when grading doesn't need top-tier reasoning.
"""
from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..specs.model import AgentSpec

from .fork_defaults import KNOWN_TOOLS
from .store import Event


logger = logging.getLogger(__name__)


_PIPE_LIMIT = 10 * 1024 * 1024
_DEFAULT_JUDGE_MODEL = "sonnet"
_OUTCOMES = ("pass", "fail", "error")


@dataclass
class JudgeResult:
    outcome: str  # 'pass' | 'fail' | 'error'
    reason: str

    def __post_init__(self):
        if self.outcome not in _OUTCOMES:
            raise ValueError(f"outcome must be one of {_OUTCOMES}, got {self.outcome!r}")


class Judge(ABC):
    """Pluggable verdict-emitter. Phase 3 ships LLMJudge; future phases may
    add code-based judges (deterministic predicates) under the same ABC."""

    @abstractmethod
    async def judge(
        self,
        spec: AgentSpec,
        prompt: str,
        events: list[Event],
    ) -> JudgeResult:
        ...


class LLMJudge(Judge):
    """Grades an agent run by asking another claude instance.

    Verdict format: the judge MUST emit one line starting with `PASS:` or
    `FAIL:` followed by a short reason. Anything else → outcome=error,
    which the daemon also treats as a run failure.
    """

    def __init__(
        self,
        binary: str = "claude",
        default_model: str = _DEFAULT_JUDGE_MODEL,
    ):
        self.binary = binary
        self.default_model = default_model

    async def judge(
        self,
        spec: AgentSpec,
        prompt: str,
        events: list[Event],
    ) -> JudgeResult:
        criteria = (spec.qa or {}).get("criteria")
        if not criteria:
            # No criteria → vacuous pass (daemon shouldn't have called us, but be safe)
            return JudgeResult("pass", "no qa criteria")

        model = (spec.qa or {}).get("judge_model") or self.default_model
        transcript = _format_transcript(events)
        judge_prompt = _build_prompt(criteria, prompt, transcript)

        # Judge gets NO tools — denylist everything; it should reason from
        # the transcript alone, not poke the filesystem.
        deny = " ".join(sorted(KNOWN_TOOLS))
        cmd = [
            self.binary,
            "--output-format", "text",
            "--system-prompt",
            (
                "You are a strict QA judge. You read a description of pass criteria "
                "and the transcript of an agent run, and you emit a single-line "
                "verdict. Reply with EXACTLY ONE line, formatted as:\n"
                "PASS: <one short reason>\n"
                "or\n"
                "FAIL: <one short reason>\n"
                "Do not output anything else."
            ),
            "--model", model,
            "--disallowedTools", deny,
            "--dangerously-skip-permissions",
            "-p", judge_prompt,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_PIPE_LIMIT,
            )
        except FileNotFoundError:
            return JudgeResult("error", f"judge binary not found: {self.binary}")
        except Exception as exc:
            return JudgeResult("error", f"judge launch failed: {exc}")

        stdout_bytes, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            err = stderr_bytes.decode("utf-8", errors="replace").strip()[:300]
            return JudgeResult("error", f"judge exited {proc.returncode}: {err or '(no stderr)'}")

        text = stdout_bytes.decode("utf-8", errors="replace").strip()
        return _parse_verdict(text)


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


def _build_prompt(criteria: str, original_prompt: str, transcript: str) -> str:
    return (
        f"Pass criteria: {criteria}\n\n"
        f"Original user prompt: {original_prompt}\n\n"
        f"Agent transcript:\n{transcript}\n\n"
        "Verdict (one line, PASS: or FAIL: only):"
    )


def _parse_verdict(text: str) -> JudgeResult:
    """Pull the first PASS:/FAIL: line out of the judge's reply."""
    if not text:
        return JudgeResult("error", "judge returned empty output")
    first_line = text.split("\n", 1)[0].strip()
    upper = first_line.upper()
    if upper.startswith("PASS:"):
        reason = first_line[len("PASS:"):].strip() or "ok"
        return JudgeResult("pass", reason)
    if upper.startswith("FAIL:"):
        reason = first_line[len("FAIL:"):].strip() or "criteria not met"
        return JudgeResult("fail", reason)
    # Tolerate when the judge skipped the prefix and just gave a reason —
    # treat as error so the daemon can still record + surface it. (Strict
    # parse keeps the spec/judge contract honest.)
    return JudgeResult("error", f"unparseable judge response: {text[:200]}")
