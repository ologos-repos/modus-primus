"""Tests for intent_router._parse_decision — the schema-validation /
fallback layer that protects the dispatch path from malformed classifier
output.

The HTTP path (IntentClassifier.classify) is exercised via the deployed
smoke; here we just verify the parser's defensive behavior.
"""
from __future__ import annotations

import json

from intent_router import (
    AgentCatalogEntry,
    IntentDecision,
    _parse_decision,
)


def _catalog() -> list[AgentCatalogEntry]:
    return [
        AgentCatalogEntry(name="check-services", domain="ops"),
        AgentCatalogEntry(name="hello-world", domain="dev"),
    ]


def test_parse_well_formed_spawn():
    raw = json.dumps({
        "action": "spawn_agent",
        "agent": "check-services",
        "agent_prompt": "check nginx",
        "reasoning": "operator named the service explicitly",
    })
    d = _parse_decision(raw, _catalog())
    assert d.action == "spawn_agent"
    assert d.agent == "check-services"
    assert d.agent_prompt == "check nginx"


def test_parse_well_formed_chat():
    raw = json.dumps({"action": "chat", "reasoning": "general question"})
    d = _parse_decision(raw, _catalog())
    assert d.action == "chat"
    assert d.agent is None


def test_unknown_agent_falls_back_to_chat():
    raw = json.dumps({
        "action": "spawn_agent",
        "agent": "nonexistent",
        "agent_prompt": "x",
    })
    d = _parse_decision(raw, _catalog())
    assert d.action == "chat"
    assert "unknown agent" in d.reasoning


def test_missing_agent_prompt_falls_back_to_chat():
    raw = json.dumps({
        "action": "spawn_agent",
        "agent": "check-services",
        "agent_prompt": "",
    })
    d = _parse_decision(raw, _catalog())
    assert d.action == "chat"
    assert "agent_prompt" in d.reasoning


def test_empty_response_falls_back_to_chat():
    d = _parse_decision("", _catalog())
    assert d.action == "chat"
    assert "empty" in d.reasoning


def test_non_json_with_braces_is_recovered():
    raw = 'Sure!\n```json\n{"action": "chat", "reasoning": "fine"}\n```'
    d = _parse_decision(raw, _catalog())
    assert d.action == "chat"


def test_garbage_falls_back_to_chat():
    d = _parse_decision("not json at all", _catalog())
    assert d.action == "chat"


def test_unknown_action_falls_back_to_chat():
    raw = json.dumps({"action": "explode", "reasoning": "trolling"})
    d = _parse_decision(raw, _catalog())
    assert d.action == "chat"
