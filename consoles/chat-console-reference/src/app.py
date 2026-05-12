"""Console app spine — aiohttp routes for turn submission + resumable streaming.

Phase 1 chunk 2: streaming substrate only. Provider integration (chunk 3),
auth (chunk 4), harness (chunk 5), and frontend (chunk 6) layer on later.

Run: `python -m console.app` (from repo root) or `bin/run.sh`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import web

from harness import HarnessUnavailable, fetch_harness_state
from history import SessionHistory
from sessions import SessionRegistry
from turns import TurnBuffer, TurnEvent, TurnRegistry

logger = logging.getLogger(__name__)

# Provider/Generator: callable accepting (buf, prompt, *, session_id, is_new_session).
# Broad alias because the call sites pass keyword args; tests use simpler stubs
# that accept **kwargs.
Generator = Callable[..., Awaitable[None]]

REGISTRY_KEY: web.AppKey[TurnRegistry] = web.AppKey("registry", TurnRegistry)
GENERATOR_KEY: web.AppKey[Generator] = web.AppKey("generator", object)  # type: ignore[arg-type]
SESSIONS_KEY: web.AppKey[SessionRegistry] = web.AppKey("sessions", SessionRegistry)
HISTORY_KEY: web.AppKey[SessionHistory] = web.AppKey("history", SessionHistory)


async def echo_generator(
    buf: TurnBuffer,
    prompt: str,
    *,
    session_id: str = "",
    is_new_session: bool = False,
) -> None:
    """Stub generator. Emits each whitespace-separated word as a token event
    with a small delay so streaming behavior is observable. Useful for ad-hoc
    smoke tests; production runs use ClaudeCliProvider via make_provider().
    """
    try:
        await buf.start()
        for word in prompt.split():
            await buf.append(TurnEvent(type="token", data={"text": word + " "}))
            await asyncio.sleep(0.05)
        await buf.finish()
    except Exception as e:
        await buf.finish(error=str(e))


def build_app(generator: Generator | None = None) -> web.Application:
    if generator is None:
        # Lazy import so tests can inject without paying provider import cost
        from providers import make_provider

        generator = make_provider()
    app = web.Application()
    data_dir = Path(os.environ.get("CHAT_CONSOLE_TURNS", "./data/turns")).resolve()
    history_path = Path(
        os.environ.get("CHAT_CONSOLE_HISTORY", "./data/history.sqlite")
    ).resolve()
    app[REGISTRY_KEY] = TurnRegistry(data_dir=data_dir)
    app[GENERATOR_KEY] = generator
    app[SESSIONS_KEY] = SessionRegistry()
    app[HISTORY_KEY] = SessionHistory(history_path)
    # Backfill any disk-only turns (sidecar metadata recovers session_id)
    # so a console.service restart doesn't lose recently-completed turns
    # whose history-write was racing with a crash. Idempotent UPSERT.
    backfilled = app[HISTORY_KEY].backfill_from_disk(data_dir)
    if backfilled:
        logger.info("history backfill: ingested %d turn(s) from disk", backfilled)

    app.router.add_post("/turns", create_turn)
    app.router.add_get("/turns/{turn_id}", get_turn)
    app.router.add_post("/turns/{turn_id}/events", inject_event)
    app.router.add_get("/sessions", list_sessions)
    app.router.add_get("/sessions/{session_id}", get_session)
    app.router.add_patch("/sessions/{session_id}", patch_session)
    app.router.add_delete("/sessions/{session_id}", delete_session)
    app.router.add_get("/sessions/{session_id}/turns", list_session_turns)
    app.router.add_get(
        "/sessions/{session_id}/turns/{turn_id}", get_session_turn
    )
    app.router.add_get("/harness/state", get_harness_state)
    app.router.add_post("/uploads", create_upload)
    app.router.add_post("/render/diagram", render_diagram)
    app.router.add_get("/render/diagram/{fname}", get_rendered_diagram)
    app.router.add_get("/healthz", healthz)

    # Frontend: serve index at / and assets at /static/.
    # Agent fleet was decoupled into its own service per chat-console#19; chat
    # only retains a configurable sidebar link (AGENTS_CONSOLE_URL).
    web_dir = Path(__file__).parent / "web"
    index_path = web_dir / "index.html"
    sw_path = web_dir / "static" / "sw.js"

    static_dir = web_dir / "static"

    def _asset_version() -> str:
        """Cache-busting tag derived from the newest mtime under web/static.
        Bumps automatically on any deploy that updates JS/CSS, so browsers
        revalidate without operators having to hard-refresh.
        """
        try:
            newest = max(
                p.stat().st_mtime
                for p in static_dir.rglob("*")
                if p.is_file()
            )
            return str(int(newest))
        except (OSError, ValueError):
            return "0"

    async def serve_index(_req: web.Request) -> web.Response:
        agents_url = os.environ.get(
            "AGENTS_CONSOLE_URL", "http://localhost:8081/agents-console"
        )
        persona = os.environ.get("CHAT_CONSOLE_PERSONA_NAME", "chat console")
        model = (
            os.environ.get("CHAT_CONSOLE_MODEL")
            or os.environ.get("OLLAMA_MODEL")
            or ""
        )
        html = index_path.read_text()
        html = html.replace("{{AGENTS_CONSOLE_URL}}", agents_url)
        html = html.replace("{{PERSONA_NAME}}", persona)
        html = html.replace("{{MODEL_NAME}}", model)
        html = html.replace("{{ASSET_VERSION}}", _asset_version())
        return web.Response(text=html, content_type="text/html")

    async def serve_sw(_req: web.Request) -> web.FileResponse:
        # Service worker must be served at root scope so it controls "/",
        # not just "/static/". Same file as /static/sw.js.
        return web.FileResponse(sw_path)

    app.router.add_static("/static/", path=str(web_dir / "static"), name="static")
    app.router.add_get("/sw.js", serve_sw)
    app.router.add_get("/", serve_index)
    return app


async def healthz(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def create_turn(request: web.Request) -> web.Response:
    """Submit a turn — synchronous (chat-console#28).

    Body: {prompt, session_id?}.
    - `session_id` omitted: server mints a UUID, provider creates a new session.
    - `session_id` provided: provider resumes that session.

    Blocks until the turn completes. Returns the full event log so the client
    can render everything in one pass. Long turns (claude with many tool calls,
    minutes) hold the connection open; client recovery on dropped connection
    is handled by the durable history sqlite + page-load restoreSession path.

    Returns 200 with {turn_id, session_id, status, error, events: [...]}.
    """
    body = await request.json()
    prompt = body.get("prompt", "")
    if not prompt:
        return web.json_response({"error": "prompt required"}, status=400)

    requested_session = body.get("session_id")
    is_new_session = not requested_session
    session_id = requested_session or str(uuid.uuid4())

    registry = request.app[REGISTRY_KEY]
    generator = request.app[GENERATOR_KEY]
    sessions = request.app[SESSIONS_KEY]
    history = request.app[HISTORY_KEY]
    buf = registry.create(session_id=session_id)

    try:
        await generator(
            buf, prompt, session_id=session_id, is_new_session=is_new_session
        )
    finally:
        sessions.record_turn_from_events(session_id, list(buf._events))
        history.record_turn(
            turn_id=buf.turn_id,
            session_id=session_id,
            prompt=prompt,
            events_jsonl="\n".join(buf._events),
            status=buf.status.value,
            error=buf.error,
            completed_at=time.time(),
        )

    # Parse the JSONL event lines into plain dicts for the response.
    events = []
    for line in buf._events:
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return web.json_response({
        "turn_id": buf.turn_id,
        "session_id": session_id,
        "status": buf.status.value,
        "error": buf.error,
        "events": events,
    })


async def get_turn(request: web.Request) -> web.Response:
    turn_id = request.match_info["turn_id"]
    registry = request.app[REGISTRY_KEY]
    buf = registry.get(turn_id)
    if buf is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(
        {
            "turn_id": buf.turn_id,
            "session_id": buf.session_id,
            "status": buf.status.value,
            "event_count": buf.event_count,
            "error": buf.error,
        }
    )


async def create_upload(request: web.Request) -> web.Response:
    """Save an uploaded file to disk so the prompt can reference it via @<path>.

    Multipart form field `file` (single). Returns `{path, name, size}`.
    Path is absolute so claude's Read tool resolves it regardless of cwd.
    """
    reader = await request.multipart()
    field = None
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "file":
            field = part
            break
    if field is None:
        return web.json_response({"error": "file field required"}, status=400)

    raw_filename = field.filename or "upload.bin"
    safe_name = "".join(
        c if c.isalnum() or c in "._-" else "_" for c in raw_filename
    )[:120] or "upload.bin"
    upload_dir = (
        Path(os.environ.get("[ENTERPRISE: env var]", "./data/uploads")).resolve()
    )
    upload_dir.mkdir(parents=True, exist_ok=True)
    final_path = upload_dir / f"{uuid.uuid4().hex[:8]}-{safe_name}"

    size = 0
    with final_path.open("wb") as f:
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            size += len(chunk)
            if size > 50 * 1024 * 1024:  # 50MB cap
                f.close()
                final_path.unlink(missing_ok=True)
                return web.json_response(
                    {"error": "file too large (max 50MB)"}, status=413
                )
            f.write(chunk)
    return web.json_response(
        {"path": str(final_path), "name": raw_filename, "size": size}
    )


async def get_harness_state(request: web.Request) -> web.Response:
    """Live chat-console state for the sidebar. ?force=true bypasses the TTL cache.

    Returns 503 with `{available: false, error}` when CHAT_CONSOLE_WORKSPACE is unset or
    the session-start script is missing — the UI then hides the sidebar.
    """
    force = request.query.get("force", "").lower() in ("1", "true", "yes")
    try:
        data = await fetch_harness_state(force=force)
    except HarnessUnavailable as e:
        return web.json_response(
            {"available": False, "error": str(e)}, status=503
        )
    return web.json_response({"available": True, **data})


_LOCALHOST_REMOTES = {"127.0.0.1", "::1"}


async def inject_event(request: web.Request) -> web.Response:
    """Append a single event into a live turn buffer from a sibling service.

    Used by the agents service to push `agent_completion` events back into
    the chat turn that spawned the run (decoupled successor to the in-process
    InChatNotifier — see chat-console#19).

    Auth: localhost-only. Both services run on the same box; if that ever
    changes, swap the IP check for a shared-token env var.
    """
    if request.remote not in _LOCALHOST_REMOTES:
        return web.json_response({"error": "forbidden"}, status=403)

    turn_id = request.match_info["turn_id"]
    registry = request.app[REGISTRY_KEY]
    buf = registry.get(turn_id)
    if buf is None:
        return web.json_response({"error": "not found"}, status=404)

    body = await request.json()
    event_type = body.get("type")
    if not event_type:
        return web.json_response({"error": "type required"}, status=400)
    data = body.get("data") or {}
    if not isinstance(data, dict):
        return web.json_response({"error": "data must be an object"}, status=400)

    await buf.append(TurnEvent(type=event_type, data=data))
    return web.json_response({"ok": True}, status=202)


# ---- Kroki diagram-render proxy (chat-console#36) ----
# POST /render/diagram for the initial render (chat dispatch).
# GET /render/diagram/{id}.{svg|png} for content-addressable retrieval —
# gives each rendered diagram a stable URL that iPhone Safari (etc.) can
# open in a new tab, long-press to save, or share. Per JD's remote-iPhone
# constraint: in-tab inline render is the primary surface, but a real
# URL is what makes it sharable.

_KROKI_ENGINES = frozenset({
    "actdiag", "blockdiag", "bpmn", "bytefield", "c4plantuml", "d2", "dbml",
    "diagramsnet", "ditaa", "dot", "erd", "excalidraw", "graphviz", "mermaid",
    "nomnoml", "nwdiag", "packetdiag", "pikchr", "plantuml", "rackdiag",
    "seqdiag", "structurizr", "svgbob", "symbolator", "tikz", "umlet", "vega",
    "vegalite", "wavedrom", "wireviz",
})
_KROKI_FORMATS = frozenset({"svg", "png"})

# Cache by render_id = sha256(engine|source)[:32]. Each entry holds the
# source so any format can be lazily rendered on demand (e.g., GET .png
# after the initial render was .svg). LRU-evicted on overflow.
_RENDER_CACHE: dict[str, dict] = {}
_RENDER_CACHE_MAX = 256
_RENDER_CACHE_ORDER: list[str] = []


def _render_id(engine: str, source: str) -> str:
    import hashlib
    return hashlib.sha256(f"{engine}|{source}".encode()).hexdigest()[:32]


def _cache_get_or_create(engine: str, source: str) -> tuple[str, dict]:
    rid = _render_id(engine, source)
    entry = _RENDER_CACHE.get(rid)
    if entry is None:
        entry = {"engine": engine, "source": source, "formats": {}}
        _RENDER_CACHE[rid] = entry
        _RENDER_CACHE_ORDER.append(rid)
        while len(_RENDER_CACHE_ORDER) > _RENDER_CACHE_MAX:
            evict = _RENDER_CACHE_ORDER.pop(0)
            _RENDER_CACHE.pop(evict, None)
    return rid, entry


async def _kroki_render(engine: str, fmt: str, source: str) -> tuple[str, bytes]:
    """POST to local Kroki; raise on failure. Returns (content_type, body)."""
    kroki_url = os.environ.get("KROKI_URL", "http://127.0.0.1:8000")
    import aiohttp as _aiohttp
    timeout = _aiohttp.ClientTimeout(total=15)
    async with _aiohttp.ClientSession(timeout=timeout) as sess:
        async with sess.post(
            f"{kroki_url}/{engine}/{fmt}",
            data=source.encode(),
            headers={"Content-Type": "text/plain"},
        ) as resp:
            payload = await resp.read()
            ctype = resp.headers.get(
                "Content-Type",
                "image/svg+xml" if fmt == "svg" else "image/png",
            )
            if resp.status != 200:
                raise RuntimeError(f"kroki {resp.status}: {payload.decode(errors='replace').strip()}")
            return ctype, payload


async def _ensure_format(entry: dict, fmt: str) -> tuple[str, bytes]:
    """Render `fmt` from the cached source if not already present."""
    if fmt not in entry["formats"]:
        ctype, payload = await _kroki_render(entry["engine"], fmt, entry["source"])
        entry["formats"][fmt] = (ctype, payload)
    return entry["formats"][fmt]


async def render_diagram(request: web.Request) -> web.Response:
    """Render a diagram via Kroki. Returns the rendered bytes plus an
    X-Render-Id header so the client can build a content-addressable URL
    (GET /render/diagram/{id}.{fmt}) for sharing or opening in a new tab."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    engine = (body.get("engine") or "").lower()
    source = body.get("source") or ""
    fmt = (body.get("format") or "svg").lower()
    if engine not in _KROKI_ENGINES:
        return web.json_response(
            {"error": f"unknown engine: {engine}"}, status=400
        )
    if fmt not in _KROKI_FORMATS:
        return web.json_response(
            {"error": f"unknown format: {fmt}"}, status=400
        )
    if not source.strip():
        return web.json_response({"error": "source required"}, status=400)

    rid, entry = _cache_get_or_create(engine, source)
    cached_already = fmt in entry["formats"]
    try:
        ctype, payload = await _ensure_format(entry, fmt)
    except RuntimeError as e:
        # Distinguish kroki-side errors (likely user syntax) from connection
        # failures (Kroki down). RuntimeError carries Kroki's own message.
        return web.json_response({"error": str(e)}, status=502)
    except Exception as e:
        return web.json_response(
            {"error": f"kroki unreachable: {e}"}, status=503
        )
    return web.Response(
        body=payload,
        content_type=ctype,
        headers={
            "X-Render-Id": rid,
            "X-Render-Cache": "hit" if cached_already else "miss",
        },
    )


async def get_rendered_diagram(request: web.Request) -> web.Response:
    """Content-addressable retrieval of a previously-rendered diagram.
    URL: GET /render/diagram/{id}.{svg|png}.

    Lazily renders the requested format from the cached source if a
    different format was the original POST. Returns 404 only if the id
    is not in cache (LRU-evicted or never rendered)."""
    fname = request.match_info["fname"]
    if "." not in fname:
        return web.Response(status=404, text="not found")
    rid, fmt = fname.rsplit(".", 1)
    fmt = fmt.lower()
    if fmt not in _KROKI_FORMATS:
        return web.Response(status=404, text="unsupported format")
    entry = _RENDER_CACHE.get(rid)
    if entry is None:
        return web.Response(status=404, text="not in cache")
    try:
        ctype, payload = await _ensure_format(entry, fmt)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=502)
    return web.Response(
        body=payload,
        content_type=ctype,
        headers={
            # Short cache so iPhone Safari can render efficiently when
            # JD opens the URL multiple times. Stable id = stable content.
            "Cache-Control": "max-age=3600",
        },
    )


async def get_session(request: web.Request) -> web.Response:
    """Return SessionState as JSON. Used by the UI to render the context-usage
    meter and surface wrap advice when the input-token budget is filling up."""
    session_id = request.match_info["session_id"]
    sessions = request.app[SESSIONS_KEY]
    state = sessions.get(session_id)
    if state is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(state.to_dict())


async def list_sessions(request: web.Request) -> web.Response:
    """Aggregated session list for the sidebar (chat-console#30). Returns the
    50 most-recently-active sessions with title + metadata."""
    limit = int(request.query.get("limit", "50"))
    history = request.app[HISTORY_KEY]
    sessions = history.list_sessions(limit=limit)
    return web.json_response({"sessions": sessions})


async def patch_session(request: web.Request) -> web.Response:
    """Set a custom title for a session (rename, chat-console#30).

    Body: {title: str}. Cap at 200 chars server-side as a sanity bound.
    Empty title clears the custom value (falls back to derived title).
    """
    session_id = request.match_info["session_id"]
    body = await request.json()
    title = body.get("title")
    if title is None or not isinstance(title, str):
        return web.json_response({"error": "title (string) required"}, status=400)
    title = title.strip()[:200]
    history = request.app[HISTORY_KEY]
    history.set_custom_title(session_id, title)
    return web.json_response({"ok": True, "session_id": session_id, "title": title})


async def delete_session(request: web.Request) -> web.Response:
    """Permanently delete a session — history rows, custom title, on-disk
    turn JSONLs, sidecar metas, and any in-memory registry buffers.

    Idempotent: deleting an unknown session_id returns ok with deleted=0.
    """
    session_id = request.match_info["session_id"]
    history = request.app[HISTORY_KEY]
    registry = request.app[REGISTRY_KEY]
    data_dir = Path(
        os.environ.get("CHAT_CONSOLE_TURNS")
        or os.environ.get("THINX_TURNS")
        or "./turns"
    )

    turn_ids = history.delete_session(session_id)

    # Drop matching live registry buffers (1h retention may still hold them).
    for tid in list(registry._turns.keys()):
        buf = registry._turns.get(tid)
        if buf is not None and buf.session_id == session_id:
            registry._turns.pop(tid, None)
            registry._created_at.pop(tid, None)
            if tid not in turn_ids:
                turn_ids.append(tid)

    # Sweep on-disk turn artifacts. Match by exact turn_id from history; also
    # sweep any orphan meta sidecars whose session_id matches (covers turns
    # that were registry-only when they were created).
    removed_files = 0
    for tid in turn_ids:
        for suffix in (".jsonl", ".meta.json"):
            p = data_dir / f"{tid}{suffix}"
            if p.exists():
                try:
                    p.unlink()
                    removed_files += 1
                except OSError:
                    pass
    if data_dir.exists():
        for meta_path in data_dir.glob("*.meta.json"):
            try:
                meta = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if meta.get("session_id") != session_id:
                continue
            jsonl_path = data_dir / f"{meta.get('turn_id', '')}.jsonl"
            for p in (meta_path, jsonl_path):
                if p.exists():
                    try:
                        p.unlink()
                        removed_files += 1
                    except OSError:
                        pass

    return web.json_response({
        "ok": True,
        "session_id": session_id,
        "deleted_turns": len(turn_ids),
        "removed_files": removed_files,
    })


async def list_session_turns(request: web.Request) -> web.Response:
    """Ordered list of turns for a session — used by the chat surface on
    page load to rehydrate the conversation (chat-console#27).

    Returns each turn with `source: "buffer"` if it's still in the live
    TurnRegistry (i.e., a turn that just finished or is in flight), or
    `source: "history"` if it's only in the durable sqlite. Empty list if
    the session has no recorded turns.
    """
    session_id = request.match_info["session_id"]
    history = request.app[HISTORY_KEY]
    registry = request.app[REGISTRY_KEY]

    history_turns = history.list_turns(session_id)
    summaries: list[dict] = []
    history_ids = set()
    for ht in history_turns:
        s = ht.to_summary()
        # Prefer "buffer" if the turn is also resident in the live registry —
        # the live data is fresher (in-flight events not yet flushed to
        # history). list_turns already returns ordered by started_at.
        if registry.get(ht.turn_id) is not None:
            s["source"] = "buffer"
        history_ids.add(ht.turn_id)
        summaries.append(s)

    # Live in-flight turns may exist in the registry without a history row
    # yet (history is written in run_and_record's finally block). Append
    # any registry-only turns at the end so the client sees them.
    for tid, buf in registry._turns.items():
        if buf.session_id != session_id or tid in history_ids:
            continue
        summaries.append({
            "turn_id": tid,
            "session_id": session_id,
            "started_at": registry._created_at.get(tid),
            "completed_at": None,
            "status": buf.status.value,
            "error": buf.error,
            "prompt": "",
            "source": "buffer",
        })
    summaries.sort(key=lambda s: s.get("started_at") or 0)
    return web.json_response({"session_id": session_id, "turns": summaries})


async def get_session_turn(request: web.Request) -> web.Response:
    """Return the full event log for a history-sourced turn so the client
    can replay it through the existing handleEvent path (chat-console#27).

    Buffer-sourced turns continue to be replayed via the existing SSE
    `/turns/{turn_id}/stream?from=0` endpoint (live, with status frame).
    """
    session_id = request.match_info["session_id"]
    turn_id = request.match_info["turn_id"]
    history = request.app[HISTORY_KEY]
    ht = history.get_turn(turn_id)
    if ht is None or ht.session_id != session_id:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({
        "turn_id": ht.turn_id,
        "session_id": ht.session_id,
        "started_at": ht.started_at,
        "completed_at": ht.completed_at,
        "status": ht.status,
        "error": ht.error,
        "prompt": ht.prompt,
        "events": ht.events,
    })


def main():
    logging.basicConfig(level=logging.INFO)
    host = os.environ.get("CONSOLE_HOST", "0.0.0.0")
    port = int(os.environ.get("CONSOLE_PORT", "8080"))
    web.run_app(build_app(), host=host, port=port)


if __name__ == "__main__":
    main()
