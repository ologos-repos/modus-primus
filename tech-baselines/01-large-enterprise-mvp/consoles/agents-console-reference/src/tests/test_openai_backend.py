"""Tests for OpenAIBackend — aiohttp-mocked SSE streamer."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import patch

import aiohttp
import pytest

from means.agents.runtime.openai_backend import OpenAIBackend
from means.agents.specs.model import AgentSpec


# ---------- helpers ----------


def _spec(timeout_s: int = 60) -> AgentSpec:
    return AgentSpec(
        name="x", domain="", fork="dev",
        model="openai:gpt-4o-mini", system_prompt="sys",
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
    def __init__(self, response: FakeResponse, *, raise_on_post: Optional[Exception] = None):
        self.response = response
        self.raise_on_post = raise_on_post
        self.last_url: Optional[str] = None
        self.last_headers: Optional[dict] = None
        self.last_json: Optional[dict] = None
        self.timeout: Optional[aiohttp.ClientTimeout] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def post(self, url, *, headers=None, json=None):
        self.last_url = url
        self.last_headers = headers
        self.last_json = json
        if self.raise_on_post is not None:
            raise self.raise_on_post
        return self.response


def _patch_session(fake: FakeSession):
    def _ctor(timeout=None):
        fake.timeout = timeout
        return fake
    return patch(
        "means.agents.runtime.openai_backend.aiohttp.ClientSession",
        side_effect=_ctor,
    )


# ---------- constructor ----------


def test_missing_api_key_raises_at_construction(monkeypatch):
    """No env var → RuntimeError at construction (no network call)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIBackend(model="gpt-4o-mini")


def test_explicit_key_overrides_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    b = OpenAIBackend(model="gpt-4o-mini", api_key="sk-test")
    assert b._api_key == "sk-test"


def test_repr_redacts_api_key():
    b = OpenAIBackend(model="gpt-4o-mini", api_key="sk-SECRET-VALUE")
    r = repr(b)
    assert "sk-SECRET" not in r
    assert "gpt-4o-mini" in r


# ---------- run() happy path ----------


@pytest.mark.asyncio
async def test_run_streams_tokens_then_final_usage():
    sink = FakeSink()
    fake = FakeSession(FakeResponse(200, [
        b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n',
        b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n',
        b'data: {"choices":[{"delta":{"content":" world"}}]}\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":11,"completion_tokens":3}}\n',
        b'data: [DONE]\n',
    ]))
    backend = OpenAIBackend(model="gpt-4o-mini", api_key="sk-test")
    with _patch_session(fake):
        await backend.run(_spec(), "hi", sink)

    types = [e[0] for e in sink.events]
    assert types == ["status", "token", "token", "usage"]
    assert sink.events[1][1]["text"] == "Hello"
    assert sink.events[2][1]["text"] == " world"
    usage = sink.events[3][1]
    assert usage["provider"] == "openai"
    assert usage["input_tokens"] == 11
    assert usage["output_tokens"] == 3
    assert usage["final"] is True


@pytest.mark.asyncio
async def test_run_request_body_and_headers():
    sink = FakeSink()
    fake = FakeSession(FakeResponse(200, [b'data: [DONE]\n']))
    backend = OpenAIBackend(model="gpt-4o-mini", api_key="sk-test")
    with _patch_session(fake):
        await backend.run(_spec(), "user prompt", sink)

    assert fake.last_url == "https://api.openai.com/v1/chat/completions"
    assert fake.last_headers["Authorization"] == "Bearer sk-test"
    body = fake.last_json
    assert body["model"] == "gpt-4o-mini"
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user prompt"},
    ]


@pytest.mark.asyncio
async def test_run_role_only_first_chunk_skipped():
    """Initial chunk often has `delta.role` but no content — don't emit empty token."""
    sink = FakeSink()
    fake = FakeSession(FakeResponse(200, [
        b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n',
        b'data: [DONE]\n',
    ]))
    backend = OpenAIBackend(model="gpt-4o-mini", api_key="sk-test")
    with _patch_session(fake):
        await backend.run(_spec(), "hi", sink)
    types = [e[0] for e in sink.events]
    assert types == ["status"]


@pytest.mark.asyncio
async def test_run_done_marker_halts_iteration():
    sink = FakeSink()
    fake = FakeSession(FakeResponse(200, [
        b'data: {"choices":[{"delta":{"content":"first"}}]}\n',
        b'data: [DONE]\n',
        b'data: {"choices":[{"delta":{"content":"after-done"}}]}\n',
    ]))
    backend = OpenAIBackend(model="gpt-4o-mini", api_key="sk-test")
    with _patch_session(fake):
        await backend.run(_spec(), "hi", sink)
    texts = [e[1].get("text") for e in sink.events if e[0] == "token"]
    assert texts == ["first"]


@pytest.mark.asyncio
async def test_run_blank_and_non_data_lines_ignored():
    sink = FakeSink()
    fake = FakeSession(FakeResponse(200, [
        b'\n',
        b': comment\n',
        b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
        b'data: [DONE]\n',
    ]))
    backend = OpenAIBackend(model="gpt-4o-mini", api_key="sk-test")
    with _patch_session(fake):
        await backend.run(_spec(), "hi", sink)
    types = [e[0] for e in sink.events]
    assert types == ["status", "token"]


@pytest.mark.asyncio
async def test_run_honors_timeout_from_spec():
    sink = FakeSink()
    fake = FakeSession(FakeResponse(200, [b'data: [DONE]\n']))
    backend = OpenAIBackend(model="gpt-4o-mini", api_key="sk-test")
    with _patch_session(fake):
        await backend.run(_spec(timeout_s=42), "hi", sink)
    assert fake.timeout.total == 42


# ---------- run() error paths ----------


@pytest.mark.asyncio
async def test_run_non_2xx_emits_error_no_credential_leak():
    sink = FakeSink()
    fake = FakeSession(FakeResponse(401, []))
    backend = OpenAIBackend(model="gpt-4o-mini", api_key="sk-SECRET-LEAK")
    with _patch_session(fake), pytest.raises(RuntimeError, match="401"):
        await backend.run(_spec(), "hi", sink)
    err = next(e for e in sink.events if e[0] == "error")
    assert "status=401" in err[1]["error"]
    # Defense-in-depth — api_key must NEVER appear in any sink event.
    for _, payload in sink.events:
        assert "sk-SECRET" not in repr(payload)


@pytest.mark.asyncio
async def test_run_network_error_emits_error_and_raises():
    sink = FakeSink()
    fake = FakeSession(
        FakeResponse(200, []),
        raise_on_post=aiohttp.ClientConnectorError(
            connection_key=None, os_error=OSError("refused"),
        ),
    )
    backend = OpenAIBackend(model="gpt-4o-mini", api_key="sk-test")
    with _patch_session(fake), pytest.raises(aiohttp.ClientError):
        await backend.run(_spec(), "hi", sink)
    types = [e[0] for e in sink.events]
    assert types == ["status", "error"]
