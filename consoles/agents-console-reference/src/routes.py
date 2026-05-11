"""routes.py — aiohttp routes for the agent-fleet console.

Mounted into console/app.py via `register_routes(app, ...)`. All endpoints
live under /agents and /runs (no collision with console's existing routes).

SSE stream uses polling (200ms while running, 500ms while pending). Phase
2+ can switch to an in-memory wakeup channel if perf demands; for Phase
1's single-user load, polling is fine.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Callable, Optional

from aiohttp import web

from .runtime import run as run_module
from .runtime import services as services_module
from .runtime.audit import AuditLog
from .runtime.cron import next_fire_at, parse_cron
from .runtime.notifier import HttpCallbackNotifier
from .runtime.scheduler import Scheduler, make_default_fire_fn
from .runtime.store import RunStore
from .specs.loader import (
    find_service_spec,
    find_spec,
    find_trigger_spec,
    find_workflow_spec,
    list_service_specs,
    list_specs,
    list_trigger_specs,
    list_workflow_specs,
)


_PKG_ROOT = Path(__file__).resolve().parent
_DEFAULT_DB_PATH = _PKG_ROOT / "data" / "agents.sqlite"
_DEFAULT_SPECS_ROOT = _PKG_ROOT / "specs"

# Polling cadences for the SSE stream
_POLL_INTERVAL_RUNNING = 0.2
_POLL_INTERVAL_PENDING = 0.5

# AppKeys for typed app state
STORE_KEY: web.AppKey[RunStore] = web.AppKey("agents-store", RunStore)
SPECS_ROOT_KEY: web.AppKey[Path] = web.AppKey("agents-specs-root", Path)
# chat_url is read from CHAT_CONSOLE_URL at startup; drives the HTTP-callback
# notifier that pushes agent_completion events back to the chat service.
CHAT_URL_KEY: web.AppKey[str] = web.AppKey("agents-chat-url", str)
# spawn_fn is injectable for tests so we don't actually Popen subprocesses.
SPAWN_FN_KEY: web.AppKey[object] = web.AppKey("agents-spawn-fn", object)
AUDIT_KEY: web.AppKey[AuditLog] = web.AppKey("agents-audit", AuditLog)


def register_routes(
    app: web.Application,
    *,
    db_path: Optional[Path] = None,
    specs_root: Optional[Path] = None,
    spawn_fn: Optional[Callable] = None,
    audit_path: Optional[Path] = None,
    chat_url: Optional[str] = None,
) -> None:
    """Mount agent-fleet routes into an aiohttp app.

    `chat_url` is the URL of the chat service where agent_completion
    notifications are POSTed. Falls back to CHAT_CONSOLE_URL env var, then
    to "" (notifier disabled — runs still execute but parent_turn_id
    linkage doesn't surface back in chat).
    """
    db_path = db_path or _DEFAULT_DB_PATH
    specs_root = specs_root or _DEFAULT_SPECS_ROOT

    app[STORE_KEY] = RunStore(db_path)
    app[SPECS_ROOT_KEY] = specs_root
    app[AUDIT_KEY] = AuditLog(audit_path)

    resolved_chat_url = chat_url or os.environ.get("CHAT_CONSOLE_URL", "")
    if resolved_chat_url:
        app[CHAT_URL_KEY] = resolved_chat_url
        app.on_startup.append(_start_notifier)
        app.on_cleanup.append(_stop_notifier)
    if spawn_fn is not None:
        app[SPAWN_FN_KEY] = spawn_fn

    app.router.add_get("/agents-console", _serve_agents_console)
    app.router.add_get("/agents", list_agents)
    app.router.add_get("/agents/{name}", get_agent)
    app.router.add_post("/agents/{name}/run", spawn_run)
    app.router.add_get("/approvals", list_approvals)
    app.router.add_post("/runs/{run_id}/approve", approve_run)
    app.router.add_post("/runs/{run_id}/deny", deny_run)
    app.router.add_get("/runs", list_runs)
    app.router.add_get("/runs/{run_id}", get_run)
    app.router.add_get("/runs/{run_id}/stream", stream_run)
    app.router.add_post("/runs/{run_id}/cancel", cancel_run)
    app.router.add_get("/services", list_services)
    app.router.add_get("/services/{name}", get_service)
    app.router.add_get("/workflows", list_workflows)
    app.router.add_get("/workflows/{name}", get_workflow)
    app.router.add_post("/workflows/{name}/run", spawn_workflow)
    app.router.add_get("/workflow-runs", list_workflow_runs)
    app.router.add_get("/workflow-runs/{id}", get_workflow_run)
    app.router.add_get("/triggers", list_triggers)
    app.router.add_get("/triggers/{name}", get_trigger)
    app.router.add_post("/triggers/{name}/fire", fire_trigger)
    # Phase 9: scheduler is started/stopped on app lifecycle, like the
    # in-chat notifier above. Lives in console.service's process.
    app.on_startup.append(_start_scheduler)
    app.on_cleanup.append(_stop_scheduler)


async def list_agents(request: web.Request) -> web.Response:
    specs = list_specs(request.app[SPECS_ROOT_KEY])
    return web.json_response([s.to_summary() for s in specs])


async def get_agent(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    spec = find_spec(request.app[SPECS_ROOT_KEY], name)
    if spec is None:
        return web.json_response({"error": "not found"}, status=404)
    body = spec.to_summary()
    body["system_prompt"] = spec.system_prompt
    return web.json_response(body)


async def spawn_run(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    spec = find_spec(request.app[SPECS_ROOT_KEY], name)
    if spec is None:
        return web.json_response({"error": "not found"}, status=404)

    body = await request.json()
    prompt = body.get("prompt", "")
    if not prompt:
        return web.json_response({"error": "prompt required"}, status=400)

    parent_session_id = body.get("session_id")
    parent_turn_id = body.get("turn_id")

    store = request.app[STORE_KEY]
    audit = request.app[AUDIT_KEY]
    spawn_fn = request.app.get(SPAWN_FN_KEY) or run_module._real_spawn

    # Phase 4 + 5: gate on spec.requires_approval OR spec.fork == "infraops".
    # Infraops always requires approval — spec can't opt out — because the
    # security boundary for ops runs is the human-in-the-loop checkpoint,
    # not the (pattern-bypassed-by-skip-permissions) tool restriction.
    requires_approval = spec.requires_approval or spec.fork == "infraops"
    if requires_approval:
        run = run_module.spawn(
            store=store,
            agent_name=spec.name,
            spec_hash=spec.spec_hash,
            fork=spec.fork,
            prompt=prompt,
            parent_session_id=parent_session_id,
            parent_turn_id=parent_turn_id,
            spawn_fn=spawn_fn,
            launch=False,
            initial_status="awaiting_approval",
        )
        audit.record(
            "run_spawned",
            run_id=run.run_id,
            agent_name=spec.name,
            fork=spec.fork,
            requires_approval=True,
            requires_approval_source=(
                "spec" if spec.requires_approval else "fork-policy"
            ),
            prompt_len=len(prompt),
        )
        audit.record("approval_requested", run_id=run.run_id, agent_name=spec.name)
    else:
        run = run_module.spawn(
            store=store,
            agent_name=spec.name,
            spec_hash=spec.spec_hash,
            fork=spec.fork,
            prompt=prompt,
            parent_session_id=parent_session_id,
            parent_turn_id=parent_turn_id,
            spawn_fn=spawn_fn,
        )
        audit.record(
            "run_spawned",
            run_id=run.run_id,
            agent_name=spec.name,
            fork=spec.fork,
            requires_approval=False,
            prompt_len=len(prompt),
        )

    return web.json_response(
        {
            "run_id": run.run_id,
            "agent": spec.name,
            "status": run.status,
        },
        status=202,
    )


async def list_runs(request: web.Request) -> web.Response:
    agent = request.query.get("agent")
    status = request.query.get("status")
    try:
        limit = int(request.query.get("limit", 20))
    except ValueError:
        return web.json_response({"error": "limit must be int"}, status=400)
    # Phase 8: by default exclude workflow children — they're surfaced
    # through /workflow-runs/{id} instead. Callers can opt back in with
    # ?include_workflow_steps=1 for debugging.
    include_workflow_steps = request.query.get("include_workflow_steps") == "1"
    store = request.app[STORE_KEY]
    runs = store.list_runs(
        agent_name=agent, status=status, limit=limit,
        top_level_only=not include_workflow_steps,
    )
    return web.json_response([r.to_dict() for r in runs])


async def get_run(request: web.Request) -> web.Response:
    """Return a run record. Includes an `output` field aggregated from
    the run's `token`-type events so consumers (like the chat console's
    slash-agent flow) don't have to parse the SSE stream themselves.
    """
    run_id = request.match_info["run_id"]
    store = request.app[STORE_KEY]
    run = store.get_run(run_id)
    if run is None:
        return web.json_response({"error": "not found"}, status=404)
    body = run.to_dict()
    # Aggregate token text. For done runs this is small (bounded by agent
    # spec timeout + token budget). For in-flight runs it's the partial
    # output so far — useful for live preview.
    try:
        events = store.get_events(run_id, from_seq=0)
        output = "".join(
            (e.data.get("text") or "")
            for e in events
            if e.type == "token"
        )
        body["output"] = output
    except Exception:
        body["output"] = ""
    return web.json_response(body)


async def stream_run(request: web.Request) -> web.StreamResponse:
    run_id = request.match_info["run_id"]
    try:
        from_index = int(request.query.get("from", 0))
    except ValueError:
        return web.json_response({"error": "from must be int"}, status=400)

    store = request.app[STORE_KEY]
    run = store.get_run(run_id)
    if run is None:
        return web.json_response({"error": "not found"}, status=404)

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    seen = max(0, from_index)
    try:
        while True:
            events = store.get_events(run_id, from_seq=seen)
            for ev in events:
                line = json.dumps(ev.to_dict(), separators=(",", ":"))
                await response.write(f"data: {line}\n\n".encode())
                seen = ev.seq + 1

            current = store.get_run(run_id)
            if current is None:
                await response.write(
                    b'event: status\ndata: {"status":"missing"}\n\n'
                )
                break

            if current.status in ("done", "error", "cancelled"):
                # Final drain in case events arrived during the status check
                tail = store.get_events(run_id, from_seq=seen)
                for ev in tail:
                    line = json.dumps(ev.to_dict(), separators=(",", ":"))
                    await response.write(f"data: {line}\n\n".encode())
                    seen = ev.seq + 1
                final = json.dumps(
                    {"status": current.status, "error": current.error},
                    separators=(",", ":"),
                )
                await response.write(
                    f"event: status\ndata: {final}\n\n".encode()
                )
                break

            interval = (
                _POLL_INTERVAL_RUNNING if current.status == "running"
                else _POLL_INTERVAL_PENDING
            )
            await asyncio.sleep(interval)
    except ConnectionResetError:
        # Client gone; daemon keeps running (server-authoritative).
        pass

    return response


async def _start_notifier(app: web.Application) -> None:
    notifier = HttpCallbackNotifier(
        store=app[STORE_KEY],
        chat_url=app[CHAT_URL_KEY],
    )
    task = asyncio.create_task(notifier.run_loop(), name="agents-notifier")
    app["agents-notifier"] = notifier
    app["agents-notifier-task"] = task


async def _stop_notifier(app: web.Application) -> None:
    notifier = app.get("agents-notifier")
    if notifier:
        notifier.stop()
    task = app.get("agents-notifier-task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _serve_agents_console(_request: web.Request) -> web.Response:
    """Standalone agents console page — its own URL so it can open in a
    new tab/window from the chat console's sidebar link.

    Renders {{CHAT_CONSOLE_URL}} (the user-facing back-link) — prefers
    CHAT_CONSOLE_PUBLIC_URL (Tailscale-reachable from any tailnet device)
    over CHAT_CONSOLE_URL (which may point at localhost for the internal
    HttpCallbackNotifier). Defaults to http://localhost:8080 when neither
    is set.
    """
    chat_url = (
        os.environ.get("CHAT_CONSOLE_PUBLIC_URL")
        or os.environ.get("CHAT_CONSOLE_URL")
        or "http://localhost:8080"
    )
    html = (_PKG_ROOT / "web" / "static" / "index.html").read_text()
    html = html.replace("{{CHAT_CONSOLE_URL}}", chat_url)
    return web.Response(text=html, content_type="text/html")


async def list_approvals(request: web.Request) -> web.Response:
    """All runs currently waiting for an approval decision (newest first)."""
    store = request.app[STORE_KEY]
    runs = store.list_runs(status="awaiting_approval", limit=50)
    return web.json_response([r.to_dict() for r in runs])


async def approve_run(request: web.Request) -> web.Response:
    """Approve an awaiting_approval run → launch daemon, audit the decision.

    Body: {approver, reason?}. `approver` defaults to "console-user" until
    auth lands (deferred per #17).
    """
    run_id = request.match_info["run_id"]
    store = request.app[STORE_KEY]
    audit = request.app[AUDIT_KEY]
    spawn_fn = request.app.get(SPAWN_FN_KEY) or run_module._real_spawn

    run = store.get_run(run_id)
    if run is None:
        return web.json_response({"error": "not found"}, status=404)
    if run.status != "awaiting_approval":
        return web.json_response(
            {"error": f"cannot approve from status={run.status}"},
            status=400,
        )

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    approver = body.get("approver", "console-user")
    reason = body.get("reason", "")

    # Audit BEFORE launching, so even a daemon-launch failure leaves a record.
    audit.record(
        "approval_decision",
        run_id=run_id,
        decision="approve",
        approver=approver,
        reason=reason,
    )

    # Launch — flips status to pending + records pid; daemon proceeds normally.
    pid = run_module.launch_daemon(
        store=store, run_id=run_id, spawn_fn=spawn_fn,
    )

    return web.json_response({
        "run_id": run_id,
        "status": "pending",
        "pid": pid,
    })


async def deny_run(request: web.Request) -> web.Response:
    """Deny an awaiting_approval run → flip to cancelled, audit the decision.
    Body: {approver, reason}."""
    run_id = request.match_info["run_id"]
    store = request.app[STORE_KEY]
    audit = request.app[AUDIT_KEY]

    run = store.get_run(run_id)
    if run is None:
        return web.json_response({"error": "not found"}, status=404)
    if run.status != "awaiting_approval":
        return web.json_response(
            {"error": f"cannot deny from status={run.status}"},
            status=400,
        )

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    approver = body.get("approver", "console-user")
    reason = body.get("reason", "denied")

    audit.record(
        "approval_decision",
        run_id=run_id,
        decision="deny",
        approver=approver,
        reason=reason,
    )

    store.update_status(
        run_id, "cancelled", exit_code=-1,
        error=f"denied by {approver}: {reason}",
    )

    return web.json_response({"run_id": run_id, "status": "cancelled"})


async def cancel_run(request: web.Request) -> web.Response:
    run_id = request.match_info["run_id"]
    store = request.app[STORE_KEY]
    run = store.get_run(run_id)
    if run is None:
        return web.json_response({"error": "not found"}, status=404)
    if run.status not in ("pending", "running"):
        return web.json_response(
            {"error": f"cannot cancel from status={run.status}"},
            status=400,
        )

    if run.pid:
        try:
            os.kill(run.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass  # already exited or not our process

    store.update_status(run_id, "cancelled", exit_code=-1)
    return web.json_response({"run_id": run_id, "status": "cancelled"})


# ---------- services (Phase 7) ----------


async def list_services(request: web.Request) -> web.Response:
    """List service specs with their current systemctl status merged in.
    Status calls run in parallel via asyncio.gather; total render time
    is dominated by the slowest single call."""
    specs = list_service_specs(request.app[SPECS_ROOT_KEY])
    statuses = await asyncio.gather(*[
        services_module.query_status(s.unit, scope=s.scope) for s in specs
    ])
    return web.json_response([
        {**spec.to_summary(), "status": status}
        for spec, status in zip(specs, statuses)
    ])


async def get_service(request: web.Request) -> web.Response:
    """Detail view: spec summary + status + recent journal lines."""
    name = request.match_info["name"]
    spec = find_service_spec(request.app[SPECS_ROOT_KEY], name)
    if spec is None:
        return web.json_response({"error": "not found"}, status=404)
    status, logs = await asyncio.gather(
        services_module.query_status(spec.unit, scope=spec.scope),
        services_module.query_logs(spec.unit, scope=spec.scope, n=30),
    )
    body = spec.to_summary()
    body["description"] = spec.description
    body["status"] = status
    body["logs"] = logs
    return web.json_response(body)


# ---------- workflows (Phase 8) ----------


_WORKFLOW_DAEMON_MODULE = "means.agents.runtime.workflow_daemon"


def _build_workflow_daemon_cmd(workflow_run_id: str, db_path: Path) -> list:
    """Same shape as runtime/run._build_daemon_cmd, different module."""
    import sys as _sys
    return [
        _sys.executable,
        "-m", _WORKFLOW_DAEMON_MODULE,
        "--workflow-run-id", workflow_run_id,
        "--db", str(db_path),
    ]


async def list_workflows(request: web.Request) -> web.Response:
    specs = list_workflow_specs(request.app[SPECS_ROOT_KEY])
    return web.json_response([s.to_summary() for s in specs])


async def get_workflow(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    spec = find_workflow_spec(request.app[SPECS_ROOT_KEY], name)
    if spec is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(spec.to_detail())


async def spawn_workflow(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    spec = find_workflow_spec(request.app[SPECS_ROOT_KEY], name)
    if spec is None:
        return web.json_response({"error": "not found"}, status=404)

    body = await request.json()
    prompt = body.get("prompt", "")
    if not prompt:
        return web.json_response({"error": "prompt required"}, status=400)

    store = request.app[STORE_KEY]
    spawn_fn = request.app.get(SPAWN_FN_KEY) or run_module._real_spawn

    wr = store.create_workflow_run(
        workflow_name=spec.name, spec_hash=spec.spec_hash, prompt=prompt,
    )
    cmd = _build_workflow_daemon_cmd(wr.workflow_run_id, store.db_path)
    proc = spawn_fn(cmd, run_module._REPO_ROOT)
    pid = getattr(proc, "pid", None)
    store.update_workflow_status(wr.workflow_run_id, "pending", pid=pid)

    return web.json_response(
        {
            "workflow_run_id": wr.workflow_run_id,
            "workflow": spec.name,
            "status": "pending",
            "pid": pid,
        },
        status=202,
    )


async def list_workflow_runs(request: web.Request) -> web.Response:
    try:
        limit = int(request.query.get("limit", 10))
    except ValueError:
        limit = 10
    store = request.app[STORE_KEY]
    return web.json_response([
        wr.to_dict() for wr in store.list_workflow_runs(limit=limit)
    ])


async def get_workflow_run(request: web.Request) -> web.Response:
    workflow_run_id = request.match_info["id"]
    store = request.app[STORE_KEY]
    wr = store.get_workflow_run(workflow_run_id)
    if wr is None:
        return web.json_response({"error": "not found"}, status=404)
    body = wr.to_dict()
    body["steps"] = [
        run.to_dict() for run in store.list_runs_for_workflow(workflow_run_id)
    ]
    return web.json_response(body)


# ---------- triggers (Phase 9) ----------


SCHEDULER_KEY: web.AppKey[Scheduler] = web.AppKey("agents-scheduler", Scheduler)
SCHEDULER_TASK_KEY: web.AppKey[asyncio.Task] = web.AppKey(
    "agents-scheduler-task", asyncio.Task,
)


def _trigger_to_response(spec, store: RunStore) -> dict:
    """Merge spec.to_summary() with current trigger_state + computed
    next_fire_at so the UI can show all of it in one card."""
    body = spec.to_summary()
    state = store.get_trigger_state(spec.name)
    body["last_fired_at"] = state.last_fired_at if state else None
    body["fire_count"] = state.fire_count if state else 0
    try:
        expr = parse_cron(spec.schedule)
        anchor = (state.last_fired_at if state and state.last_fired_at
                  else import_time())
        body["next_fire_at"] = next_fire_at(expr, anchor)
    except ValueError:
        body["next_fire_at"] = None
    return body


def import_time() -> float:
    import time as _time
    return _time.time()


async def list_triggers(request: web.Request) -> web.Response:
    specs = list_trigger_specs(request.app[SPECS_ROOT_KEY])
    store = request.app[STORE_KEY]
    return web.json_response([_trigger_to_response(s, store) for s in specs])


async def get_trigger(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    spec = find_trigger_spec(request.app[SPECS_ROOT_KEY], name)
    if spec is None:
        return web.json_response({"error": "not found"}, status=404)
    body = _trigger_to_response(spec, request.app[STORE_KEY])
    body["description"] = spec.description
    return web.json_response(body)


async def fire_trigger(request: web.Request) -> web.Response:
    """Manual fire — useful for testing without waiting for the cron edge.
    Records last_fired_at so the next scheduler tick doesn't double-fire
    within the same window."""
    name = request.match_info["name"]
    spec = find_trigger_spec(request.app[SPECS_ROOT_KEY], name)
    if spec is None:
        return web.json_response({"error": "not found"}, status=404)
    store = request.app[STORE_KEY]
    spawn_fn = request.app.get(SPAWN_FN_KEY) or run_module._real_spawn
    fire_fn = make_default_fire_fn(store, request.app[SPECS_ROOT_KEY], spawn_fn)
    now = import_time()
    await fire_fn(spec, now)
    store.record_trigger_fire(spec.name, now)
    return web.json_response(
        {"trigger": spec.name, "fired_at": now}, status=202,
    )


async def _start_scheduler(app: web.Application) -> None:
    """Lifecycle hook: start the in-process scheduler. The scheduler
    polls for trigger specs every 30s and fires when their cron edges
    pass. Stays a no-op for the test app fixture (which can override
    by providing its own SCHEDULER_KEY entry)."""
    if SCHEDULER_KEY in app:
        return  # tests / external code already wired one
    spawn_fn = app.get(SPAWN_FN_KEY) or run_module._real_spawn
    fire_fn = make_default_fire_fn(
        app[STORE_KEY], app[SPECS_ROOT_KEY], spawn_fn,
    )
    scheduler = Scheduler(
        store=app[STORE_KEY],
        specs_root=app[SPECS_ROOT_KEY],
        fire_fn=fire_fn,
    )
    app[SCHEDULER_KEY] = scheduler
    task = asyncio.create_task(scheduler.run_loop(), name="agents-scheduler")
    app[SCHEDULER_TASK_KEY] = task


async def _stop_scheduler(app: web.Application) -> None:
    scheduler = app.get(SCHEDULER_KEY)
    if scheduler:
        scheduler.stop()
    task = app.get(SCHEDULER_TASK_KEY)
    if task:
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
