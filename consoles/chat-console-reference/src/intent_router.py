"""Intent classifier — routes operator prompts between "chat" and "spawn-agent".

Uses Ollama's `format: <json-schema>` constrained-output mechanism (the same
pattern proven by the provisioning-agent substrate). Any Ollama-served model
can be used regardless of native tool-call support; the schema forces the
reply into a parseable shape.

Returns an IntentDecision dataclass. The orchestration layer (chat-console
provider wrapper) consumes the decision:

  - action="chat"          → fall through to the base text-generation provider
  - action="spawn_agent"   → dispatch via agents-console /agents/{name}/run

Wire-level concerns (HTTP calls to agents-console, streaming, approval gating)
live in the provider wrapper; this module is pure classification.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional, Sequence

import aiohttp

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentCatalogEntry:
    name: str
    domain: str = ""
    fork: str = ""
    description: str = ""


@dataclass(frozen=True)
class IntentDecision:
    action: str  # "chat" | "spawn_agent"
    agent: Optional[str] = None
    agent_prompt: Optional[str] = None
    reasoning: str = ""
    raw: Optional[dict] = None  # the raw classifier response for diagnostics


# JSON schema for the Ollama `format` parameter. Forces the response into
# the exact shape `IntentDecision` consumes. `agent` and `agent_prompt` are
# optional at the schema level — they're only meaningful when action is
# spawn_agent and the orchestrator handles missing values defensively.
_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["chat", "spawn_agent"],
            "description": "chat = answer directly. spawn_agent = the operator is asking to dispatch an agent run.",
        },
        "agent": {
            "type": "string",
            "description": "Agent spec name (must match one in the catalog) when action=spawn_agent.",
        },
        "agent_prompt": {
            "type": "string",
            "description": "Operator instructions to forward to the spawned agent.",
        },
        "reasoning": {
            "type": "string",
            "description": "One sentence why this classification was chosen.",
        },
    },
    "required": ["action"],
}


_SYSTEM_TEMPLATE = """You are an intent classifier for a chat console.

Decide whether the operator wants you to:

  (a) Answer them directly via chat. action="chat".

  (b) Dispatch (spawn) an agent run from this fixed catalog:
{catalog_block}

      action="spawn_agent". Set `agent` to the catalog name and
      `agent_prompt` to the natural-language instructions the agent should
      receive. The agent_prompt MUST be self-contained — the agent never
      sees the operator's exact words, only what you put here.

Rules:
  - Default to action="chat" when in doubt.
  - Only pick spawn_agent when the operator's prompt clearly asks for
    one of the catalog agents to run, OR matches its declared purpose
    closely (e.g., "check the status of foo" → check-services).
  - Discussion about agents ("what does check-services do?") is "chat",
    NOT spawn_agent.
  - Return ONLY the JSON object; no prose."""


def _format_catalog(catalog: Sequence[AgentCatalogEntry]) -> str:
    if not catalog:
        return "      (no agents currently registered)"
    lines = []
    for a in catalog:
        bits = [f"      - {a.name}"]
        if a.domain:
            bits.append(f"domain={a.domain}")
        if a.fork:
            bits.append(f"fork={a.fork}")
        line = " ".join(bits)
        if a.description:
            line += f" — {a.description}"
        lines.append(line)
    return "\n".join(lines)


class IntentClassifier:
    """Calls Ollama with format-constrained JSON to classify a prompt."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 30.0,
    ):
        self.base_url = (
            base_url or os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
        ).rstrip("/")
        # Classifier model can be overridden separately from the chat model
        # (use something fast/cheap for routing). Defaults to the chat model.
        self.model = (
            model
            or os.environ.get("CHAT_CONSOLE_INTENT_MODEL")
            or os.environ.get("OLLAMA_MODEL")
            or "gemma3:12b"
        )
        self.timeout_seconds = timeout_seconds

    async def classify(
        self,
        operator_prompt: str,
        catalog: Sequence[AgentCatalogEntry],
    ) -> IntentDecision:
        catalog_block = _format_catalog(catalog)
        system = _SYSTEM_TEMPLATE.format(catalog_block=catalog_block)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": operator_prompt},
            ],
            "format": _INTENT_SCHEMA,
            "stream": False,
            "options": {"temperature": 0.0},
        }
        url = f"{self.base_url}/api/chat"
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body) as resp:
                    if resp.status >= 300:
                        text = await resp.text()
                        logger.warning(
                            "intent classifier HTTP %d: %s", resp.status, text[:300]
                        )
                        return IntentDecision(
                            action="chat",
                            reasoning=f"classifier HTTP {resp.status}; defaulting to chat",
                        )
                    data = await resp.json()
        except Exception as e:
            logger.warning("intent classifier failed: %r", e)
            return IntentDecision(
                action="chat",
                reasoning=f"classifier transport failure: {type(e).__name__}",
            )

        content = ((data.get("message") or {}).get("content") or "").strip()
        return _parse_decision(content, catalog)


def _parse_decision(
    content: str, catalog: Sequence[AgentCatalogEntry]
) -> IntentDecision:
    """Parse the classifier's JSON response into an IntentDecision.

    Defaults to action="chat" whenever the response is malformed,
    references an unknown agent, or omits required fields — the safe
    fallback is "pass through to the chat model", never accidentally
    dispatch something.
    """
    if not content:
        return IntentDecision(action="chat", reasoning="empty classifier response")
    try:
        parsed: dict = json.loads(content)
    except json.JSONDecodeError:
        # Try to recover from markdown-wrapped or trailing-prose responses.
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                return IntentDecision(
                    action="chat", reasoning="JSON parse failed", raw={"content": content[:300]}
                )
        else:
            return IntentDecision(
                action="chat", reasoning="no JSON object", raw={"content": content[:300]}
            )

    action = (parsed.get("action") or "").strip()
    reasoning = (parsed.get("reasoning") or "")[:300]
    if action == "spawn_agent":
        agent = (parsed.get("agent") or "").strip()
        agent_prompt = (parsed.get("agent_prompt") or "").strip()
        known = {a.name for a in catalog}
        if agent not in known:
            return IntentDecision(
                action="chat",
                reasoning=f"classifier named unknown agent {agent!r}; fell back to chat",
                raw=parsed,
            )
        if not agent_prompt:
            return IntentDecision(
                action="chat",
                reasoning="classifier omitted agent_prompt; fell back to chat",
                raw=parsed,
            )
        return IntentDecision(
            action="spawn_agent",
            agent=agent,
            agent_prompt=agent_prompt,
            reasoning=reasoning,
            raw=parsed,
        )
    return IntentDecision(action="chat", reasoning=reasoning, raw=parsed)
