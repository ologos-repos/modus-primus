"""Tests for app.py routes — POST /turns, GET /turns/{id}, GET /turns/{id}/stream.

Verifies the SSE wiring: turn creation returns a turn_id, stream resumes from
offset, late subscribers see the full replay, etc.
"""
import asyncio
import json
import os
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app import REGISTRY_KEY, build_app
from turns import TurnBuffer, TurnEvent


@pytest.fixture
def turns_dir(tmp_path: Path, monkeypatch) -> Path:
    """Per-test isolation for both turn buffers AND history sqlite.

    Pre-chat-console#27, only CHAT_CONSOLE_TURNS was isolated → tests writing to /turns
    POST also wrote into the live ./data/history.sqlite (the default path
    `app.py` falls back to). That polluted JD's real chat history.
    Forcing CHAT_CONSOLE_HISTORY into tmp_path stops the cross-pollination.
    """
    d = tmp_path / "turns"
    monkeypatch.setenv("CHAT_CONSOLE_TURNS", str(d))
    monkeypatch.setenv("CHAT_CONSOLE_HISTORY", str(tmp_path / "history.sqlite"))
    return d


async def _slow_generator(
    buf: TurnBuffer, prompt: str, **_kwargs
) -> None:
    """Deterministic, slow-enough-to-observe-streaming generator for tests.
    Accepts (and ignores) the session_id/is_new_session kwargs the production
    Provider interface uses.
    """
    await buf.start()
    for i, word in enumerate(prompt.split()):
        await buf.append(TurnEvent(type="token", data={"text": word, "i": i}))
        await asyncio.sleep(0.01)
    await buf.finish()


def _parse_sse(raw: bytes) -> list[dict]:
    """Parse SSE 'data: …' frames into a list of decoded JSON payloads.
    Skips non-data frames (status events) for assertion convenience.
    """
    frames = []
    for chunk in raw.decode().split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        for line in chunk.splitlines():
            if line.startswith("data: "):
                payload = line[len("data: "):]
                try:
                    frames.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass
    return frames


async def test_index_serves_html(turns_dir):
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/")
        assert resp.status == 200
        body = await resp.text()
        assert "<!DOCTYPE html>" in body
        assert "chat console" in body
        assert "/static/style.css" in body
        assert "/static/app.js" in body


async def test_static_serves_css(turns_dir):
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/static/style.css")
        assert resp.status == 200
        body = await resp.text()
        assert "--bg" in body  # a CSS variable from our theme


async def test_static_serves_js(turns_dir):
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/static/app.js")
        assert resp.status == 200
        body = await resp.text()
        assert "chat console" in body  # appears in the file header comment


async def test_static_serves_marked(turns_dir):
    """chat-console#29: marked.js must be vendored at /static/marked.min.js so the
    chat console doesn't need a CDN fetch (PWA / offline use case)."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/static/marked.min.js")
        assert resp.status == 200
        body = await resp.text()
        # Banner identifies marked
        assert "marked" in body.lower()


async def test_index_loads_marked_before_app(turns_dir):
    """marked.js must load before app.js so window.marked is defined when
    app.js's setOptions / renderMarkdown calls run."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        body = await (await client.get("/")).text()
        idx_marked = body.find("/static/marked.min.js")
        idx_app = body.find("/static/app.js")
        assert idx_marked != -1
        assert idx_app != -1
        assert idx_marked < idx_app  # script-load order


async def test_app_js_uses_marked_for_markdown(turns_dir):
    """renderMarkdown delegates to marked.parse — confirms the swap landed."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        body = await (await client.get("/static/app.js")).text()
        assert "window.marked.parse" in body
        # Old custom regex rules should be gone — sample a few that we
        # know were in the previous renderer
        assert "FENCE${idx}" not in body  # placeholder pattern from old fence path


async def test_app_js_has_render_refactor_symbols(turns_dir):
    """chat-console#25: confirm the structural refactor symbols are present in
    the served bundle — guards against regressions that delete the
    turn-events container, token-run partitioning, or status footer."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        body = await (await client.get("/static/app.js")).text()
        # turn-events container is the new flow root for per-turn events
        assert "turn-events" in body
        # token-run partitioning helper
        assert "appendTokenToTextRun" in body
        # status footer + spinner
        assert "createStatusFooter" in body
        assert "tickStatus" in body
        assert "SPINNER_FRAMES" in body
        # tool body collapse
        assert "tool-body-summary" in body and "tool-body-full" in body


async def test_history_persists_completed_turn(turns_dir, tmp_path, monkeypatch):
    """chat-console#27: a completed turn lands in the history sqlite + is visible
    via GET /sessions/{id}/turns and GET /sessions/{id}/turns/{turn_id}."""
    monkeypatch.setenv("CHAT_CONSOLE_HISTORY", str(tmp_path / "history.sqlite"))
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        create = await client.post("/turns", json={"prompt": "alpha beta gamma"})
        body = await create.json()
        turn_id = body["turn_id"]
        session_id = body["session_id"]

        # Wait for the turn to finish
        for _ in range(500):
            sj = await (await client.get(f"/turns/{turn_id}")).json()
            if sj["status"] == "done":
                break
            await asyncio.sleep(0.01)

        # Buffer GC may not have run; let the registry's record-to-history
        # finally block complete by yielding once more.
        await asyncio.sleep(0.05)

        list_resp = await client.get(f"/sessions/{session_id}/turns")
        assert list_resp.status == 200
        listed = await list_resp.json()
        assert listed["session_id"] == session_id
        ids = [t["turn_id"] for t in listed["turns"]]
        assert turn_id in ids

        detail = await client.get(f"/sessions/{session_id}/turns/{turn_id}")
        assert detail.status == 200
        d = await detail.json()
        assert d["turn_id"] == turn_id
        assert d["session_id"] == session_id
        assert d["prompt"] == "alpha beta gamma"
        assert d["status"] == "done"
        # Three tokens → at least three events
        assert len(d["events"]) >= 3


async def test_history_orders_turns_by_started_at(turns_dir, tmp_path, monkeypatch):
    """Multiple turns in one session return in chronological order."""
    monkeypatch.setenv("CHAT_CONSOLE_HISTORY", str(tmp_path / "history.sqlite"))
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        first = await (await client.post("/turns", json={"prompt": "first"})).json()
        sid = first["session_id"]
        # Wait for first to finish
        for _ in range(500):
            if (await (await client.get(f"/turns/{first['turn_id']}")).json())["status"] == "done":
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        await client.post("/turns", json={"prompt": "second", "session_id": sid})
        for _ in range(500):
            listed = (await (await client.get(f"/sessions/{sid}/turns")).json())["turns"]
            statuses = [t["status"] for t in listed]
            if len(listed) == 2 and all(s in ("done", "error") for s in statuses):
                break
            await asyncio.sleep(0.01)
        listed = (await (await client.get(f"/sessions/{sid}/turns")).json())["turns"]
        assert len(listed) >= 2
        prompts = [t["prompt"] for t in listed]
        assert prompts[0] == "first"
        assert prompts[1] == "second"


async def test_history_empty_for_unknown_session(turns_dir, tmp_path, monkeypatch):
    """An unknown session returns empty list, not 404 — restore should be
    a no-op rather than a hard failure for new visitors."""
    monkeypatch.setenv("CHAT_CONSOLE_HISTORY", str(tmp_path / "history.sqlite"))
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/sessions/no-such-session/turns")
        assert resp.status == 200
        body = await resp.json()
        assert body["turns"] == []


async def test_history_unknown_turn_returns_404(turns_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_CONSOLE_HISTORY", str(tmp_path / "history.sqlite"))
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/sessions/whatever/turns/missing")
        assert resp.status == 404


async def test_list_sessions_returns_aggregated_titles(turns_dir, tmp_path, monkeypatch):
    """chat-console#30: GET /sessions returns ordered list with derived titles."""
    monkeypatch.setenv("CHAT_CONSOLE_HISTORY", str(tmp_path / "history.sqlite"))
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        # Two turns in two different sessions
        first = await (await client.post(
            "/turns",
            json={"prompt": "this is a longer prompt that should truncate at the boundary please"},
        )).json()
        await (await client.post("/turns", json={"prompt": "short one"})).json()
        # Allow history-write to settle
        await asyncio.sleep(0.05)

        resp = await client.get("/sessions")
        assert resp.status == 200
        body = await resp.json()
        sessions = body["sessions"]
        assert len(sessions) == 2
        # Most recent first
        titles = [s["title"] for s in sessions]
        assert "short one" in titles
        # Long prompt truncated at 40 chars + ellipsis
        long_title = next(t for t in titles if "longer" in t)
        assert len(long_title) <= 41  # 40 + ellipsis
        assert long_title.endswith("…")
        # Required fields
        for s in sessions:
            assert "session_id" in s
            assert "turn_count" in s
            assert "last_activity" in s


async def test_patch_session_sets_custom_title(turns_dir, tmp_path, monkeypatch):
    """chat-console#30: PATCH /sessions/{id} stores a user-supplied title."""
    monkeypatch.setenv("CHAT_CONSOLE_HISTORY", str(tmp_path / "history.sqlite"))
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        created = await (await client.post(
            "/turns", json={"prompt": "auto title"}
        )).json()
        sid = created["session_id"]
        await asyncio.sleep(0.05)

        resp = await client.patch(
            f"/sessions/{sid}",
            json={"title": "My Renamed Session"},
        )
        assert resp.status == 200
        assert (await resp.json())["title"] == "My Renamed Session"

        # Custom title now wins over derived
        listing = (await (await client.get("/sessions")).json())["sessions"]
        match = [s for s in listing if s["session_id"] == sid][0]
        assert match["title"] == "My Renamed Session"


async def test_patch_session_rejects_missing_title(turns_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_CONSOLE_HISTORY", str(tmp_path / "history.sqlite"))
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.patch("/sessions/anything", json={})
        assert resp.status == 400


async def test_patch_session_caps_title_length(turns_dir, tmp_path, monkeypatch):
    """200-char sanity bound."""
    monkeypatch.setenv("CHAT_CONSOLE_HISTORY", str(tmp_path / "history.sqlite"))
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        created = await (await client.post("/turns", json={"prompt": "x"})).json()
        sid = created["session_id"]
        long_title = "a" * 500
        resp = await client.patch(f"/sessions/{sid}", json={"title": long_title})
        assert resp.status == 200
        assert len((await resp.json())["title"]) == 200


async def test_delete_session_removes_history_rows_files_and_buffers(
    turns_dir, tmp_path, monkeypatch
):
    """DELETE /sessions/{id} drops history rows, custom title, on-disk turn
    artifacts, and live registry buffers belonging to the session."""
    monkeypatch.setenv("CHAT_CONSOLE_HISTORY", str(tmp_path / "history.sqlite"))
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        # Two turns in the same session.
        first = await (await client.post(
            "/turns", json={"prompt": "first"}
        )).json()
        sid = first["session_id"]
        second = await (await client.post(
            "/turns", json={"prompt": "second", "session_id": sid}
        )).json()
        # Let both turns drain to done so history rows are written.
        for tid in (first["turn_id"], second["turn_id"]):
            for _ in range(500):
                s = await (await client.get(f"/turns/{tid}")).json()
                if s["status"] in ("done", "error"):
                    break
                await asyncio.sleep(0.01)
        # Custom title so we also exercise the `sessions` row delete.
        await client.patch(f"/sessions/{sid}", json={"title": "to be gone"})

        # Pre-condition: session shows up, files exist.
        sessions = (await (await client.get("/sessions")).json())["sessions"]
        assert any(s["session_id"] == sid for s in sessions)
        for tid in (first["turn_id"], second["turn_id"]):
            assert (turns_dir / f"{tid}.jsonl").exists()
            assert (turns_dir / f"{tid}.meta.json").exists()

        # Delete + verify.
        resp = await client.delete(f"/sessions/{sid}")
        assert resp.status == 200
        body = await resp.json()
        assert body["ok"] is True
        assert body["session_id"] == sid
        assert body["deleted_turns"] >= 2

        # Session no longer in list.
        sessions = (await (await client.get("/sessions")).json())["sessions"]
        assert not any(s["session_id"] == sid for s in sessions)
        # On-disk artifacts swept.
        for tid in (first["turn_id"], second["turn_id"]):
            assert not (turns_dir / f"{tid}.jsonl").exists()
            assert not (turns_dir / f"{tid}.meta.json").exists()
        # Registry buffers cleared for this session.
        registry = app[REGISTRY_KEY]
        for buf in registry._turns.values():
            assert buf.session_id != sid


async def test_delete_unknown_session_is_idempotent(
    turns_dir, tmp_path, monkeypatch
):
    """Deleting a session that doesn't exist must succeed quietly with
    deleted_turns=0."""
    monkeypatch.setenv("CHAT_CONSOLE_HISTORY", str(tmp_path / "history.sqlite"))
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.delete("/sessions/does-not-exist")
        assert resp.status == 200
        body = await resp.json()
        assert body["ok"] is True
        assert body["deleted_turns"] == 0


async def test_turn_writes_meta_sidecar(turns_dir):
    """chat-console#27 backfill: starting a turn writes a sidecar JSON with the
    session_id so disk-only artifacts can be re-ingested into history."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        create = await client.post("/turns", json={"prompt": "hi"})
        body = await create.json()
        turn_id = body["turn_id"]
        session_id = body["session_id"]
        # Wait for the turn to start writing
        for _ in range(500):
            sj = await (await client.get(f"/turns/{turn_id}")).json()
            if sj["status"] in ("running", "done"):
                break
            await asyncio.sleep(0.01)
        meta_path = turns_dir / f"{turn_id}.meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["turn_id"] == turn_id
        assert meta["session_id"] == session_id


async def test_history_backfill_ingests_disk_turns(turns_dir, tmp_path):
    """chat-console#27 backfill: build_app's startup hook ingests any JSONL+meta
    pair on disk that isn't already in history. Simulates a console.service
    restart after a turn completed but before history-write reached disk
    (or pre-#27 turns now retrofitted with sidecar files)."""
    from history import SessionHistory
    # Fabricate a turn on disk: events JSONL + sidecar meta
    turns_dir.mkdir(parents=True, exist_ok=True)
    turn_id = "fake-turn-1"
    session_id = "fake-session-A"
    (turns_dir / f"{turn_id}.jsonl").write_text(
        '{"type":"token","data":{"text":"alpha"}}\n'
        '{"type":"token","data":{"text":" beta"}}\n'
    )
    (turns_dir / f"{turn_id}.meta.json").write_text(
        json.dumps({
            "turn_id": turn_id,
            "session_id": session_id,
            "started_at": 1700000000.0,
        })
    )
    # Backfill into a fresh history db
    history = SessionHistory(tmp_path / "history-bf.sqlite")
    inserted = history.backfill_from_disk(turns_dir)
    assert inserted == 1
    # Idempotent: second run inserts nothing
    assert history.backfill_from_disk(turns_dir) == 0
    # Recoverable via the normal API
    rows = history.list_turns(session_id)
    assert len(rows) == 1
    assert rows[0].turn_id == turn_id


async def test_history_backfill_skips_orphans_without_sidecar(turns_dir, tmp_path):
    """Pre-#27 turns have no sidecar — session_id can't be reconstructed,
    so backfill must skip them rather than guess."""
    from history import SessionHistory
    turns_dir.mkdir(parents=True, exist_ok=True)
    (turns_dir / "orphan-pre-27.jsonl").write_text(
        '{"type":"token","data":{"text":"x"}}\n'
    )
    history = SessionHistory(tmp_path / "history-orphan.sqlite")
    inserted = history.backfill_from_disk(turns_dir)
    assert inserted == 0


async def test_app_js_has_session_restore_symbols(turns_dir):
    """chat-console#27 + #28: the bundle wires up session-restore on boot."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        body = await (await client.get("/static/app.js")).text()
        assert "restoreSession" in body
        assert "replayOneTurn" in body
        # #28: synchronous wire, no SSE/EventSource/openStream
        assert "EventSource" not in body
        assert "openStream" not in body


async def test_app_css_has_render_refactor_symbols(turns_dir):
    """chat-console#25: confirm new CSS classes + spinner keyframes are served."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        body = await (await client.get("/static/style.css")).text()
        assert ".turn-events" in body
        assert ".tool-block" in body
        assert ".thinking-block" in body
        assert ".turn-status-footer" in body
        assert ".status-spinner" in body
        assert "@keyframes spinner-fade" in body


async def test_manifest_serves_valid_json(turns_dir):
    """PWA manifest must be valid JSON with the keys iOS / browsers expect."""
    import json as _json
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/static/manifest.json")
        assert resp.status == 200
        body = await resp.text()
        manifest = _json.loads(body)
        assert manifest["name"] == "chat console"
        assert manifest["short_name"]
        assert manifest["start_url"] == "/"
        assert manifest["display"] == "standalone"
        assert manifest["icons"] and len(manifest["icons"]) >= 1


async def test_sw_at_root_scope(turns_dir):
    """Service worker must serve at /sw.js (root scope) so it controls /."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/sw.js")
        assert resp.status == 200
        body = await resp.text()
        assert "serviceWorker" not in body or "self.addEventListener" in body
        assert "self.addEventListener" in body
        assert "notificationclick" in body


async def test_upload_saves_file_and_returns_path(tmp_path, monkeypatch):
    """POST /uploads accepts a multipart file, saves to [ENTERPRISE: env var], returns path."""
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("[ENTERPRISE: env var]", str(upload_dir))
    monkeypatch.setenv("CHAT_CONSOLE_TURNS", str(tmp_path / "turns"))

    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        from aiohttp import FormData
        form = FormData()
        form.add_field("file", b"hello world", filename="note.txt", content_type="text/plain")
        resp = await client.post("/uploads", data=form)
        assert resp.status == 200
        body = await resp.json()
        assert body["name"] == "note.txt"
        assert body["size"] == len(b"hello world")
        # Path is absolute and the file actually exists
        from pathlib import Path as _P
        saved = _P(body["path"])
        assert saved.is_absolute()
        assert saved.exists()
        assert saved.read_bytes() == b"hello world"


async def test_upload_sanitizes_filename(tmp_path, monkeypatch):
    """Path-traversal-style names get scrubbed."""
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("[ENTERPRISE: env var]", str(upload_dir))
    monkeypatch.setenv("CHAT_CONSOLE_TURNS", str(tmp_path / "turns"))

    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        from aiohttp import FormData
        form = FormData()
        form.add_field("file", b"x", filename="../../etc/passwd", content_type="text/plain")
        resp = await client.post("/uploads", data=form)
        assert resp.status == 200
        body = await resp.json()
        # The saved path is *under* the upload dir, regardless of original filename
        from pathlib import Path as _P
        saved = _P(body["path"])
        assert str(saved.parent.resolve()) == str(upload_dir.resolve())


async def test_upload_missing_field_returns_400(tmp_path, monkeypatch):
    monkeypatch.setenv("[ENTERPRISE: env var]", str(tmp_path / "uploads"))
    monkeypatch.setenv("CHAT_CONSOLE_TURNS", str(tmp_path / "turns"))

    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        from aiohttp import FormData
        form = FormData()
        form.add_field("not_file", b"x", filename="x.txt")
        resp = await client.post("/uploads", data=form)
        assert resp.status == 400


async def test_index_includes_pwa_meta(turns_dir):
    """index.html must declare manifest + iOS PWA meta tags so the install
    flow + standalone-mode chrome work on iPhone."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/")
        body = await resp.text()
        assert 'rel="manifest"' in body
        assert "/static/manifest.json" in body
        assert 'rel="apple-touch-icon"' in body
        assert 'name="apple-mobile-web-app-capable"' in body
        assert 'name="theme-color"' in body


async def test_healthz(turns_dir):
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/healthz")
        assert resp.status == 200
        assert (await resp.json())["ok"] is True


async def test_index_substitutes_agents_url(turns_dir, monkeypatch):
    """AGENTS_CONSOLE_URL replaces the {{AGENTS_CONSOLE_URL}} token in the sidebar link."""
    monkeypatch.setenv("AGENTS_CONSOLE_URL", "http://agents.example:9001/agents-console")
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/")
        body = await resp.text()
        assert 'href="http://agents.example:9001/agents-console"' in body
        assert "{{AGENTS_CONSOLE_URL}}" not in body


async def test_index_default_agents_url(turns_dir, monkeypatch):
    """When AGENTS_CONSOLE_URL is unset, sidebar link defaults to localhost:8081."""
    monkeypatch.delenv("AGENTS_CONSOLE_URL", raising=False)
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/")
        body = await resp.text()
        assert 'href="http://localhost:8081/agents-console"' in body


async def test_index_no_longer_references_agents_static(turns_dir):
    """After chat-console#19 decoupling, the chat HTML must not load /agents-static/* assets."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/")
        body = await resp.text()
        assert "/agents-static/" not in body
        assert 'id="fleet-panel"' not in body


async def test_create_turn_returns_completed_turn(turns_dir):
    """chat-console#28: POST /turns is now synchronous — blocks until the turn
    finishes and returns the full event log."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post("/turns", json={"prompt": "hello world"})
        assert resp.status == 200
        body = await resp.json()
        assert "turn_id" in body
        assert "session_id" in body
        assert body["status"] == "done"
        assert body["error"] is None
        # Two-word prompt → two token events from _slow_generator
        events = body["events"]
        token_texts = [e["data"]["text"] for e in events if e["type"] == "token"]
        assert token_texts == ["hello", "world"]


async def test_create_turn_rejects_empty_prompt(turns_dir):
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post("/turns", json={"prompt": ""})
        assert resp.status == 400


async def test_get_turn_unknown_returns_404(turns_dir):
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/turns/nonexistent")
        assert resp.status == 404


# SSE stream tests removed (chat-console#28) — no /turns/{id}/stream endpoint anymore.
# Synchronous POST returns the full event log directly; see
# test_create_turn_returns_completed_turn above.


async def test_create_turn_returns_session_id_for_new_conversation(turns_dir):
    """Omitting session_id starts a new conversation; server mints UUID."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post("/turns", json={"prompt": "hi"})
        body = await resp.json()
        assert "session_id" in body
        # Should look like a UUID (36 chars with dashes)
        assert len(body["session_id"]) == 36
        assert body["session_id"].count("-") == 4


async def test_create_turn_preserves_provided_session_id(turns_dir):
    """Passing session_id continues that conversation; server returns same id."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(
            "/turns",
            json={"prompt": "follow up", "session_id": "abc-123-existing"},
        )
        body = await resp.json()
        assert body["session_id"] == "abc-123-existing"


async def test_get_turn_includes_session_id(turns_dir):
    """GET /turns/{id} surfaces the session_id (debugging + client recovery)."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        create = await client.post("/turns", json={"prompt": "hi"})
        body = await create.json()
        turn_id = body["turn_id"]
        session_id = body["session_id"]

        get = await client.get(f"/turns/{turn_id}")
        get_body = await get.json()
        assert get_body["session_id"] == session_id


async def test_provider_receives_session_kwargs(turns_dir):
    """Verify the provider gets (session_id, is_new_session) per request."""
    captured = []

    async def capturing_gen(buf: TurnBuffer, prompt: str, **kwargs):
        captured.append(kwargs)
        await buf.start()
        await buf.finish()

    app = build_app(generator=capturing_gen)
    async with TestServer(app) as server, TestClient(server) as client:
        # New conversation
        resp = await client.post("/turns", json={"prompt": "first"})
        first_session = (await resp.json())["session_id"]
        # Continue same conversation
        await client.post(
            "/turns", json={"prompt": "second", "session_id": first_session}
        )
        # Wait for both background tasks to land
        for _ in range(200):
            if len(captured) == 2:
                break
            await asyncio.sleep(0.01)

    assert len(captured) == 2
    assert captured[0]["is_new_session"] is True
    assert captured[0]["session_id"] == first_session
    assert captured[1]["is_new_session"] is False
    assert captured[1]["session_id"] == first_session


async def test_harness_state_503_when_unavailable(turns_dir, monkeypatch):
    """No CHAT_CONSOLE_WORKSPACE → 503 with available:false; UI hides sidebar."""
    monkeypatch.delenv("CHAT_CONSOLE_WORKSPACE", raising=False)
    import harness as harness_pkg
    harness_pkg.reset_cache()

    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/harness/state")
        assert resp.status == 503
        body = await resp.json()
        assert body["available"] is False
        assert "error" in body


async def test_harness_state_returns_session_start_payload(turns_dir, tmp_path, monkeypatch):
    """Mocked subprocess returns a session-start JSON; route surfaces it."""
    import json as _json
    from unittest.mock import AsyncMock, patch

    import harness as harness_pkg
    harness_pkg.reset_cache()

    scripts = tmp_path / "means" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "session-start.py").write_text("# stub\n")
    monkeypatch.setenv("CHAT_CONSOLE_WORKSPACE", str(tmp_path))

    fake_payload = _json.dumps(
        {
            "timestamp": "2026-05-07T13:00:00+00:00",
            "git": {
                "branch": "main",
                "head": "abc1234",
                "clean": True,
                "uncommitted": [],
                "ahead": 0,
                "behind": 0,
            },
            "services": [{"unit": "[ENTERPRISE: personal chat bridge service].service", "active": True}],
            "commits": ["abc1234 console: chunk 5"],
            "meta_context": [],
            "cross_ai": [],
        }
    ).encode()

    class _FakeProc:
        def __init__(self, stdout, returncode=0):
            self._stdout = stdout
            self.returncode = returncode

        async def communicate(self):
            return self._stdout, b""

    with patch(
        "harness.state.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_FakeProc(fake_payload)),
    ):
        app = build_app(generator=_slow_generator)
        async with TestServer(app) as server, TestClient(server) as client:
            resp = await client.get("/harness/state")
            assert resp.status == 200
            body = await resp.json()
            assert body["available"] is True
            assert body["git"]["branch"] == "main"
            assert body["services"][0]["unit"] == "[ENTERPRISE: personal chat bridge service].service"


async def test_get_session_unknown_returns_404(turns_dir):
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.get("/sessions/never-seen")
        assert resp.status == 404


async def test_session_stats_recorded_after_turn(turns_dir):
    """Provider emits a usage event; server scans the buffer post-turn and
    records into SessionRegistry. GET /sessions/{id} reflects it."""

    async def usage_emitting_gen(buf: TurnBuffer, prompt: str, *, session_id, **_):
        await buf.start()
        await buf.append(TurnEvent(type="token", data={"text": "hi"}))
        await buf.append(
            TurnEvent(
                type="usage",
                data={
                    "input_tokens": 4,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 25_000,
                    "output_tokens": 12,
                    "total_input_tokens": 25_004,
                    "final": True,
                    "total_cost_usd": 0.05,
                },
            )
        )
        await buf.finish()

    app = build_app(generator=usage_emitting_gen)
    async with TestServer(app) as server, TestClient(server) as client:
        create = await client.post("/turns", json={"prompt": "hi"})
        body = await create.json()
        sid = body["session_id"]
        # Wait for the run_and_record wrapper to land
        for _ in range(200):
            resp = await client.get(f"/sessions/{sid}")
            if resp.status == 200:
                break
            await asyncio.sleep(0.01)

        assert resp.status == 200
        stats = await resp.json()
        assert stats["session_id"] == sid
        assert stats["turn_count"] == 1
        assert stats["last_input_tokens"] == 25_004
        assert stats["last_output_tokens"] == 12
        assert stats["is_above_warn"] is False  # 25K << 150K default threshold
        assert stats["advice"] is None


async def test_session_advice_at_warn_threshold(turns_dir, monkeypatch):
    """Sets threshold low and verifies the advice surfaces in the API."""
    monkeypatch.setenv("CONSOLE_SESSION_WARN_TOKENS", "100")
    monkeypatch.setenv("CONSOLE_SESSION_HARD_TOKENS", "1000")

    async def gen(buf: TurnBuffer, prompt: str, *, session_id, **_):
        await buf.start()
        await buf.append(
            TurnEvent(
                type="usage",
                data={
                    "input_tokens": 0,
                    "cache_read_input_tokens": 200,
                    "output_tokens": 1,
                    "total_input_tokens": 200,
                    "final": True,
                },
            )
        )
        await buf.finish()

    app = build_app(generator=gen)
    async with TestServer(app) as server, TestClient(server) as client:
        create = await client.post("/turns", json={"prompt": "x"})
        sid = (await create.json())["session_id"]
        for _ in range(200):
            resp = await client.get(f"/sessions/{sid}")
            if resp.status == 200 and (await resp.json())["turn_count"] >= 1:
                break
            await asyncio.sleep(0.01)
        stats = await resp.json()
        assert stats["is_above_warn"] is True
        assert stats["advice"] is not None
        assert "filling up" in stats["advice"].lower()


# test_generation_continues_after_subscriber_disconnect removed (chat-console#28) —
# subscribers are gone; the synchronous POST owns the connection and the
# turn returns when it's done.


async def test_inject_event_appends_to_buffer(turns_dir):
    """POST /turns/{id}/events from localhost appends one event into the live buffer."""
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        create = await client.post(
            "/turns", json={"prompt": "x x x x x x x x x x"}
        )
        turn_id = (await create.json())["turn_id"]

        resp = await client.post(
            f"/turns/{turn_id}/events",
            json={
                "type": "agent_completion",
                "data": {"run_id": "r-1", "status": "done"},
            },
        )
        assert resp.status == 202
        assert (await resp.json())["ok"] is True

        for _ in range(500):
            status_resp = await client.get(f"/turns/{turn_id}")
            if (await status_resp.json())["status"] == "done":
                break
            await asyncio.sleep(0.01)

        final = await (await client.get(f"/turns/{turn_id}")).json()
        assert final["event_count"] == 11  # 10 tokens + 1 injected


async def test_inject_event_unknown_turn_returns_404(turns_dir):
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(
            "/turns/does-not-exist/events",
            json={"type": "agent_completion", "data": {}},
        )
        assert resp.status == 404


async def test_inject_event_requires_type(turns_dir):
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        create = await client.post("/turns", json={"prompt": "hi"})
        turn_id = (await create.json())["turn_id"]
        resp = await client.post(
            f"/turns/{turn_id}/events", json={"data": {}}
        )
        assert resp.status == 400


# SSE id-line / Last-Event-ID / keepalive tests removed (chat-console#28) — the
# SSE wire is gone. Synchronous POST returns the full event log; recovery
# is via durable history sqlite + page-load restore, not stream resume.


async def test_inject_event_rejects_non_localhost(turns_dir, monkeypatch):
    """Spoof request.remote to a non-loopback IP — endpoint must reject."""
    from app import _LOCALHOST_REMOTES  # noqa: F401  ensures import path stable
    app = build_app(generator=_slow_generator)
    async with TestServer(app) as server, TestClient(server) as client:
        create = await client.post("/turns", json={"prompt": "hi"})
        turn_id = (await create.json())["turn_id"]

        # Patch the property so the request looks like it came from elsewhere.
        from aiohttp import web as aiohttp_web
        original = aiohttp_web.BaseRequest.remote
        monkeypatch.setattr(
            aiohttp_web.BaseRequest, "remote",
            property(lambda self: "10.0.0.42"),
        )
        try:
            resp = await client.post(
                f"/turns/{turn_id}/events",
                json={"type": "agent_completion", "data": {}},
            )
            assert resp.status == 403
        finally:
            monkeypatch.setattr(aiohttp_web.BaseRequest, "remote", original)
