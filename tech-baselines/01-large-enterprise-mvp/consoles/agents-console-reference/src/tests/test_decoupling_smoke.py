"""Cross-service smoke test for [ENTERPRISE: tracker ref] decoupling.

Boots both the chat console and the agents service as separate aiohttp
TestServers (separate ports). Verifies:

1. Agent run with parent_turn_id terminates → notifier POSTs to chat's
   /turns/{turn_id}/events endpoint.
2. Chat appends the event into the parent turn's buffer.
3. End-to-end: agents has no reference to chat's TurnRegistry; chat has
   no reference to means.agents — they communicate exclusively over HTTP.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

# Make the console package importable for this test (it lives in a sibling
# directory, not in the same Python package as means/agents/).
_THINX_ROOT = Path(__file__).resolve().parents[3]
_CONSOLE_DIR = _THINX_ROOT / "console"
sys.path.insert(0, str(_CONSOLE_DIR))

from means.agents.routes import register_routes  # noqa: E402
from means.agents.runtime.notifier import HttpCallbackNotifier  # noqa: E402
from means.agents.runtime.store import RunStore  # noqa: E402


@pytest.fixture
async def chat_server(tmp_path: Path, monkeypatch):
    """Real chat aiohttp app on a TestServer (random port)."""
    monkeypatch.setenv("AGENTS_CONSOLE_TURNS", str(tmp_path / "chat-turns"))
    # Isolate AGENTS_CONSOLE_HISTORY too so the test doesn't write into the live
    # ./data/history.sqlite (lesson from #27 follow-up).
    monkeypatch.setenv("AGENTS_CONSOLE_HISTORY", str(tmp_path / "history.sqlite"))
    from app import build_app as build_chat_app  # imported after path setup

    async def _slow_generator(buf, prompt, **_kwargs):
        from turns import TurnEvent
        await buf.start()
        for word in prompt.split():
            await buf.append(TurnEvent(type="token", data={"text": word}))
            await asyncio.sleep(0.005)
        await buf.finish()

    app = build_chat_app(generator=_slow_generator)
    server = TestServer(app)
    await server.start_server()
    try:
        yield server
    finally:
        await server.close()


async def test_agent_completion_round_trips_via_http(chat_server, tmp_path):
    """Spawn an agent run with parent_turn_id, terminate it, verify the
    chat-side turn buffer receives the agent_completion event."""

    chat_url = f"http://127.0.0.1:{chat_server.port}"

    # Step 1: Create a chat turn so its TurnBuffer exists.
    async with TestClient(chat_server) as chat_client:
        create_resp = await chat_client.post(
            "/turns", json={"prompt": "hello world"}
        )
        body = await create_resp.json()
        turn_id = body["turn_id"]

        # Wait for the chat turn's buffer to start receiving events.
        for _ in range(200):
            status = await chat_client.get(f"/turns/{turn_id}")
            sj = await status.json()
            if sj["event_count"] >= 1:
                break
            await asyncio.sleep(0.01)

        # Step 2: Set up an agents-side store with a terminal run linked
        # back to that chat turn. We don't need the full agents app for the
        # callback — just the notifier hitting the chat's HTTP endpoint.
        store = RunStore(tmp_path / "agents.sqlite")
        run = store.create_run(
            agent_name="hello-world",
            spec_hash="h",
            fork="dev",
            prompt="agent prompt",
            parent_turn_id=turn_id,
            parent_session_id=body["session_id"],
        )
        store.update_status(run.run_id, "done", exit_code=0)

        # Step 3: Run one notifier pass (real HTTP, real chat).
        notifier = HttpCallbackNotifier(store=store, chat_url=chat_url)
        # run_loop sets up the session; we want one-shot, so do it manually.
        import aiohttp
        notifier._session = aiohttp.ClientSession()
        try:
            delivered = await notifier.check_and_notify()
        finally:
            await notifier._session.close()

        assert delivered == 1
        assert run.run_id in notifier.notified

        # Step 4: Verify chat buffer received the agent_completion event.
        # Wait for the original generator to finish so the JSONL is stable.
        for _ in range(500):
            st = await (await chat_client.get(f"/turns/{turn_id}")).json()
            if st["status"] == "done":
                break
            await asyncio.sleep(0.01)

        # The /turns/{id}/stream endpoint was removed in [ENTERPRISE: tracker ref] (sync
        # pivot). Verify the inject landed via the on-disk JSONL — the
        # buffer's append() writes through to disk, so the agent_completion
        # event is durably visible there. This is also the data path the
        # history-backfill uses.
        from turns import TurnRegistry  # noqa: E402
        registry = chat_server.app[__import__("app").REGISTRY_KEY]
        buf = registry.get(turn_id)
        assert buf is not None
        events = buf._events
        assert any("agent_completion" in line for line in events), \
            f"agent_completion not found in {len(events)} events"
        assert any(run.run_id in line for line in events)


async def test_agents_app_does_not_import_console(chat_server):
    """Sanity: the agents package must remain free of console imports."""
    import means.agents
    import means.agents.routes
    import means.agents.runtime.notifier

    # No module under means.agents.* should have console.* in its source.
    for mod in (
        means.agents,
        means.agents.routes,
        means.agents.runtime.notifier,
    ):
        if not hasattr(mod, "__file__") or mod.__file__ is None:
            continue
        src = Path(mod.__file__).read_text()
        assert "from console" not in src, (
            f"{mod.__name__} imports from console — coupling regression"
        )
        assert "import console" not in src, (
            f"{mod.__name__} imports console — coupling regression"
        )


async def test_chat_app_does_not_import_means_agents(chat_server):
    """Sanity: the chat app must not import means.agents anywhere."""
    import app as console_app
    src = Path(console_app.__file__).read_text()
    assert "means.agents" not in src, (
        "console/app.py still references means.agents — decoupling incomplete"
    )
