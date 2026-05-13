"""Tests for the spawn-vocabulary regex used by IntentRoutingProvider's
false-negative safety net.

Goal: when the operator's prompt clearly asks for a dispatch (spawn /
run / dispatch / invoke an agent), the router treats it as a spawn
request even if the format-constrained classifier returned chat. The
regex must be strict enough to NOT fire on meta-questions about agents
(e.g. "what does the agent do?").
"""
from __future__ import annotations

from providers.intent_routing import _looks_like_spawn_request


# Should match — operator uses spawn verb + the word "agent" within
# proximity. The regex's purpose is to catch the false-negative case
# where the classifier mis-routes a generic "spawn an agent" request to
# chat; explicit-by-name spawns ("run hello-world …") are expected to
# get spawn_agent from the classifier directly and don't need this
# fallback path.
SPAWN_PROMPTS = [
    "spawn an agent that will count the number of planets",
    "spawn an agent to build a simple lamp stack",
    "Spawn an Agent for me please",
    "dispatch an agent to fetch the news",
    "invoke an agent that does X",
    "kick off an agent for me",
    "fire up the check-services agent",
    "execute an agent that summarizes my notes",
    "start an agent to do X",
    "run an agent to verify the deploy",
]


# Should NOT match — these are conversational or meta-questions.
NON_SPAWN_PROMPTS = [
    "what does the hello-world agent do?",
    "explain how agents work",
    "tell me about agents",
    "is there an agent for status checks?",
    "list the agents in the catalog",
    "can agents read files?",
    "what is the difference between agents and tools?",
    "summarize this paragraph",  # plain chat
    "explain E=MC^2",
    "hi",
]


def test_spawn_vocabulary_matches_dispatch_intents():
    for p in SPAWN_PROMPTS:
        assert _looks_like_spawn_request(p), f"missed spawn intent: {p!r}"


def test_spawn_vocabulary_skips_meta_and_unrelated():
    for p in NON_SPAWN_PROMPTS:
        assert not _looks_like_spawn_request(p), (
            f"false positive on non-spawn prompt: {p!r}"
        )
