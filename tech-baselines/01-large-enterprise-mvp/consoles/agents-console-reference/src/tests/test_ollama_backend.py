"""Tests for OllamaBackend — aiohttp-mocked.

Mocks `aiohttp.ClientSession` with a hand-rolled async context manager that
streams canned NDJSON bytes. No new dev dep — same approach as the
subprocess-mocked ClaudeCliBackend tests.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import aiohttp
import pytest

from means.agents.runtime.ollama_backend import OllamaBackend
from means.agents.specs.model import AgentSpec


# ---------- helpers ----------


def _spec(timeout_s: int = 60) -> AgentSpec:
    return AgentSpec(
        name="x", domain="", fork="dev",
        model="ollama:peakai/qwen3:14b", system_prompt="sys",
        timeout_s=timeout_s, tools=[], qa={}, cwd=None, requires_approval=False,
        spec_path=Path("/x.md"), spec_hash="h",
    )


class FakeSink:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, data: dict) -> int:
        self.events.append((event_type, data))
        return len(self.events) - 1


class FakeResponseContent:
    """Mimics the async iterator on aiohttp's StreamReader."""

    def __init__(self, lines: list[bytes]):
        self._lines = lines

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for line in self._lines:
            yield line


class FakeResponse:
    def __init__(self, status: int, lines: list[bytes]):
        self.status = status
        self.content = FakeResponseContent(lines)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """Records the last call args; returns canned response."""

    def __init__(
        self,
        response: FakeResponse,
        *,
        raise_on_post: Optional[Exception] = None,
        timeout: Optional[aiohttp.ClientTimeout] = None,
    ):
        self.response = response
        self.raise_on_post = raise_on_post
        self.timeout = timeout
        self.last_url: Optional[str] = None
        self.last_json: Optional[dict] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def post(self, url, *, json=None):
        self.last_url = url
        self.last_json = json
        if self.raise_on_post is not None:
            raise self.raise_on_post
        return self.response


def _patch_session(fake: FakeSession):
    """Replace aiohttp.ClientSession in the ollama_backend module with a
    constructor that returns `fake`. Captures the timeout for assertions."""
    def _ctor(timeout=None):
        fake.timeout = timeout
        return fake
    return patch(
        "means.agents.runtime.ollama_backend.aiohttp.ClientSession",
        side_effect=_ctor,
    )


# ---------- constructor ----------


def test_unknown_alias_raises_at_construction():
    """No network call, no run() needed — alias check runs in __init__."""
    with pytest.raises(ValueError, match="unknown ollama host alias"):
        OllamaBackend(
            hosts={"peakai": "http://x"}, host_alias="ghost",
            model_tag="qwen3:14b",
        )


def test_constructor_stores_normalized_url():
    """Trailing slash on the host URL is stripped so the {url}/api/chat
    join doesn't double-slash."""
    b = OllamaBackend(
        hosts={"peakai": "http://x:11434/"}, host_alias="peakai",
        model_tag="qwen3:14b",
    )
    assert "//" not in b._base_url[7:]  # skip http://


def test_repr_does_not_leak_host_url():
    """Defense-in-depth: a backend's repr shouldn't include the full URL
    (no api_key here, but same principle as the keyed providers)."""
    b = OllamaBackend(
        hosts={"peakai": "http://10.0.0.5:11434"}, host_alias="peakai",
        model_tag="qwen3:14b",
    )
    assert "10.0.0.5" not in repr(b)
    assert "peakai" in repr(b)


# ---------- run() happy path ----------


@pytest.mark.asyncio
async def test_run_streams_tokens_then_final_usage():
    sink = FakeSink()
    fake_resp = FakeResponse(
        200,
        [
            b'{"message":{"content":"Hello"},"done":false}\n',
            b'{"message":{"content":" world"},"done":false}\n',
            b'{"message":{"content":"!"},"done":true,"prompt_eval_count":7,"eval_count":3}\n',
        ],
    )
    fake = FakeSession(fake_resp)
    backend = OllamaBackend(
        hosts={"peakai": "http://x:11434"}, host_alias="peakai",
        model_tag="qwen3:14b",
    )
    with _patch_session(fake):
        await backend.run(_spec(), "hi", sink)

    types = [e[0] for e in sink.events]
    assert types == ["status", "token", "token", "token", "usage"]
    assert sink.events[0] == ("status", {"status": "running"})
    assert sink.events[1][1]["text"] == "Hello"
    assert sink.events[3][1]["text"] == "!"
    usage = sink.events[4][1]
    assert usage["final"] is True
    assert usage["provider"] == "ollama"
    assert usage["input_tokens"] == 7
    assert usage["output_tokens"] == 3


@pytest.mark.asyncio
async def test_run_request_body_shape():
    sink = FakeSink()
    fake = FakeSession(FakeResponse(200, [b'{"done":true}\n']))
    backend = OllamaBackend(
        hosts={"peakai": "http://x:11434"}, host_alias="peakai",
        model_tag="qwen3:14b",
    )
    with _patch_session(fake):
        await backend.run(_spec(), "user prompt here", sink)

    assert fake.last_url == "http://x:11434/api/chat"
    body = fake.last_json
    assert body["model"] == "qwen3:14b"
    assert body["stream"] is True
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user prompt here"},
    ]


@pytest.mark.asyncio
async def test_run_honors_timeout_from_spec():
    sink = FakeSink()
    fake = FakeSession(FakeResponse(200, [b'{"done":true}\n']))
    backend = OllamaBackend(
        hosts={"peakai": "http://x:11434"}, host_alias="peakai",
        model_tag="qwen3:14b",
    )
    with _patch_session(fake):
        await backend.run(_spec(timeout_s=42), "hi", sink)
    assert fake.timeout is not None
    assert fake.timeout.total == 42


@pytest.mark.asyncio
async def test_run_skips_empty_content_blocks():
    """The first chunk often has no content (role-only); don't emit empty token."""
    sink = FakeSink()
    fake = FakeSession(
        FakeResponse(
            200,
            [
                b'{"message":{"role":"assistant","content":""},"done":false}\n',
                b'{"message":{"content":"actual"},"done":true,"prompt_eval_count":1,"eval_count":1}\n',
            ],
        )
    )
    backend = OllamaBackend(
        hosts={"peakai": "http://x:11434"}, host_alias="peakai",
        model_tag="qwen3:14b",
    )
    with _patch_session(fake):
        await backend.run(_spec(), "hi", sink)
    types = [e[0] for e in sink.events]
    assert types == ["status", "token", "usage"]


@pytest.mark.asyncio
async def test_run_tolerates_garbage_lines():
    """A malformed JSON line shouldn't crash the run."""
    sink = FakeSink()
    fake = FakeSession(
        FakeResponse(
            200,
            [
                b'not-json-at-all\n',
                b'{"message":{"content":"ok"},"done":true}\n',
            ],
        )
    )
    backend = OllamaBackend(
        hosts={"peakai": "http://x:11434"}, host_alias="peakai",
        model_tag="qwen3:14b",
    )
    with _patch_session(fake):
        await backend.run(_spec(), "hi", sink)
    types = [e[0] for e in sink.events]
    assert types == ["status", "token", "usage"]


# ---------- run() error paths ----------


@pytest.mark.asyncio
async def test_run_non_2xx_emits_error_and_raises():
    sink = FakeSink()
    fake = FakeSession(FakeResponse(503, []))
    backend = OllamaBackend(
        hosts={"peakai": "http://x:11434"}, host_alias="peakai",
        model_tag="qwen3:14b",
    )
    with _patch_session(fake), pytest.raises(RuntimeError, match="503"):
        await backend.run(_spec(), "hi", sink)
    types = [e[0] for e in sink.events]
    assert "error" in types
    err = next(e for e in sink.events if e[0] == "error")
    assert "status=503" in err[1]["error"]


@pytest.mark.asyncio
async def test_run_network_error_emits_error_and_raises():
    sink = FakeSink()
    fake = FakeSession(
        FakeResponse(200, []),
        raise_on_post=aiohttp.ClientConnectorError(
            connection_key=None, os_error=OSError("refused"),
        ),
    )
    backend = OllamaBackend(
        hosts={"peakai": "http://x:11434"}, host_alias="peakai",
        model_tag="qwen3:14b",
    )
    with _patch_session(fake), pytest.raises(aiohttp.ClientError):
        await backend.run(_spec(), "hi", sink)
    types = [e[0] for e in sink.events]
    assert types == ["status", "error"]
