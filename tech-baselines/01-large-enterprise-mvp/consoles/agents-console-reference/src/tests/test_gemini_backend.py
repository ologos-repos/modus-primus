"""Tests for GeminiBackend — aiohttp-mocked SSE streamer."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import patch

import aiohttp
import pytest

from means.agents.runtime.gemini_backend import GeminiBackend
from means.agents.specs.model import AgentSpec


# ---------- helpers ----------


def _spec(timeout_s: int = 60) -> AgentSpec:
    return AgentSpec(
        name="x", domain="", fork="dev",
        model="gemini:gemini-2.5-flash", system_prompt="sys",
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
        self.last_json: Optional[dict] = None
        self.timeout: Optional[aiohttp.ClientTimeout] = None

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
    def _ctor(timeout=None):
        fake.timeout = timeout
        return fake
    return patch(
        "means.agents.runtime.gemini_backend.aiohttp.ClientSession",
        side_effect=_ctor,
    )


# ---------- constructor ----------


def test_missing_api_key_raises_at_construction(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiBackend(model="gemini-2.5-flash")


def test_repr_redacts_api_key():
    b = GeminiBackend(model="gemini-2.5-flash", api_key="AIza-SECRET-VALUE")
    r = repr(b)
    assert "AIza-SECRET" not in r
    assert "gemini-2.5-flash" in r


# ---------- run() happy path ----------


@pytest.mark.asyncio
async def test_run_streams_tokens_then_final_usage():
    sink = FakeSink()
    fake = FakeSession(FakeResponse(200, [
        b'data: {"candidates":[{"content":{"parts":[{"text":"Hello"}]}}]}\n',
        b'data: {"candidates":[{"content":{"parts":[{"text":" world"}]}}]}\n',
        b'data: {"candidates":[{"content":{"parts":[{"text":"!"}]}}],'
        b'"usageMetadata":{"promptTokenCount":9,"candidatesTokenCount":3}}\n',
    ]))
    backend = GeminiBackend(model="gemini-2.5-flash", api_key="AIza-test")
    with _patch_session(fake):
        await backend.run(_spec(), "hi", sink)

    types = [e[0] for e in sink.events]
    assert types == ["status", "token", "token", "token", "usage"]
    assert sink.events[1][1]["text"] == "Hello"
    assert sink.events[3][1]["text"] == "!"
    usage = sink.events[4][1]
    assert usage["provider"] == "gemini"
    assert usage["input_tokens"] == 9
    assert usage["output_tokens"] == 3
    assert usage["final"] is True


@pytest.mark.asyncio
async def test_run_concatenates_multiple_parts_in_one_event():
    """A single SSE event can carry multiple text parts; emit them in order."""
    sink = FakeSink()
    fake = FakeSession(FakeResponse(200, [
        b'data: {"candidates":[{"content":{"parts":['
        b'{"text":"foo"},{"text":"bar"},{"text":"baz"}'
        b']}}]}\n',
    ]))
    backend = GeminiBackend(model="gemini-2.5-flash", api_key="AIza-test")
    with _patch_session(fake):
        await backend.run(_spec(), "hi", sink)
    texts = [e[1]["text"] for e in sink.events if e[0] == "token"]
    assert texts == ["foo", "bar", "baz"]


@pytest.mark.asyncio
async def test_run_uses_latest_usage_metadata():
    """If multiple events carry usageMetadata, the trailing one wins."""
    sink = FakeSink()
    fake = FakeSession(FakeResponse(200, [
        b'data: {"candidates":[{"content":{"parts":[{"text":"a"}]}}],'
        b'"usageMetadata":{"promptTokenCount":1,"candidatesTokenCount":1}}\n',
        b'data: {"candidates":[{"content":{"parts":[{"text":"b"}]}}],'
        b'"usageMetadata":{"promptTokenCount":1,"candidatesTokenCount":2}}\n',
    ]))
    backend = GeminiBackend(model="gemini-2.5-flash", api_key="AIza-test")
    with _patch_session(fake):
        await backend.run(_spec(), "hi", sink)
    usage = next(e[1] for e in sink.events if e[0] == "usage")
    assert usage["output_tokens"] == 2


@pytest.mark.asyncio
async def test_run_url_includes_model_and_streamGenerateContent():
    sink = FakeSink()
    fake = FakeSession(FakeResponse(200, []))
    backend = GeminiBackend(model="gemini-2.5-flash", api_key="AIza-test")
    with _patch_session(fake):
        await backend.run(_spec(), "hi", sink)
    assert "gemini-2.5-flash:streamGenerateContent" in fake.last_url
    assert "alt=sse" in fake.last_url
    body = fake.last_json
    assert body["systemInstruction"]["parts"] == [{"text": "sys"}]
    assert body["contents"] == [{"role": "user", "parts": [{"text": "hi"}]}]


@pytest.mark.asyncio
async def test_run_honors_timeout_from_spec():
    sink = FakeSink()
    fake = FakeSession(FakeResponse(200, []))
    backend = GeminiBackend(model="gemini-2.5-flash", api_key="AIza-test")
    with _patch_session(fake):
        await backend.run(_spec(timeout_s=42), "hi", sink)
    assert fake.timeout.total == 42


# ---------- run() error paths ----------


@pytest.mark.asyncio
async def test_run_non_2xx_emits_error_no_credential_or_url_leak():
    """Gemini error bodies can echo the request key. Verify the error
    event payload has neither URL nor key — only a redacted status."""
    sink = FakeSink()
    fake = FakeSession(FakeResponse(403, []))
    backend = GeminiBackend(model="gemini-2.5-flash", api_key="AIza-LEAK-IF-EXPOSED")
    with _patch_session(fake), pytest.raises(RuntimeError, match="403"):
        await backend.run(_spec(), "hi", sink)
    err = next(e for e in sink.events if e[0] == "error")
    assert "status=403" in err[1]["error"]
    for _, payload in sink.events:
        text = repr(payload)
        assert "AIza-LEAK" not in text
        assert "googleapis.com" not in text


@pytest.mark.asyncio
async def test_run_network_error_emits_error_and_raises():
    sink = FakeSink()
    fake = FakeSession(
        FakeResponse(200, []),
        raise_on_post=aiohttp.ClientConnectorError(
            connection_key=None, os_error=OSError("refused"),
        ),
    )
    backend = GeminiBackend(model="gemini-2.5-flash", api_key="AIza-test")
    with _patch_session(fake), pytest.raises(aiohttp.ClientError):
        await backend.run(_spec(), "hi", sink)
    types = [e[0] for e in sink.events]
    assert types == ["status", "error"]
