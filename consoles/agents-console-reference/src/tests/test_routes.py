"""Tests for routes.py — list/get specs, spawn run, list/get/stream/cancel
runs. Spawn is exercised with an injected fake spawn_fn (no actual
subprocess). Stream is verified against pre-populated events.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from means.agents.routes import (
    AUDIT_KEY,
    SPAWN_FN_KEY,
    STORE_KEY,
    register_routes,
)


# ---------- fixtures ----------


def _write_spec(root: Path, name: str, body: str = "you are a helper") -> Path:
    p = root / f"{name}.md"
    p.write_text(f"---\nmodel: claude-sonnet-4-7\nfork: dev\n---\n{body}")
    return p


class FakeProc:
    def __init__(self, pid: int = 99999):
        self.pid = pid


def _fake_spawn(cmd, cwd):
    return FakeProc(pid=99999)


@pytest.fixture
def specs_root(tmp_path: Path) -> Path:
    root = tmp_path / "specs"
    root.mkdir()
    _write_spec(root, "hello-world")
    return root


@pytest.fixture
async def client(tmp_path: Path, specs_root: Path):
    """An aiohttp TestClient with the agent routes mounted."""
    app = web.Application()
    register_routes(
        app,
        db_path=tmp_path / "agents.sqlite",
        specs_root=specs_root,
        spawn_fn=_fake_spawn,
        audit_path=tmp_path / "audit.jsonl",
    )
    async with TestServer(app) as server:
        async with TestClient(server) as c:
            yield c


# ---------- /agents ----------


async def test_agents_console_serves_html(client: TestClient):
    """Standalone agents-console page — opens in a new tab from the chat sidebar link."""
    resp = await client.get("/agents-console")
    assert resp.status == 200
    body = await resp.text()
    assert "<!DOCTYPE html>" in body
    assert "agents console" in body.lower()
    assert "fleet-panel" in body
    # Self-contained static paths after [ENTERPRISE: tracker ref] decoupling
    assert "/static/agents.js" in body
    assert "/static/agents.css" in body
    assert "/static/style.css" in body


async def test_agents_console_substitutes_chat_url(client: TestClient, monkeypatch):
    """CHAT_CONSOLE_URL env replaces the {{CHAT_CONSOLE_URL}} token in the back-link."""
    monkeypatch.setenv("CHAT_CONSOLE_URL", "http://chat.example:9000")
    resp = await client.get("/agents-console")
    body = await resp.text()
    assert 'href="http://chat.example:9000"' in body
    assert "{{CHAT_CONSOLE_URL}}" not in body


async def test_agents_console_default_chat_url(client: TestClient, monkeypatch):
    """When CHAT_CONSOLE_URL is unset, the back-link defaults to localhost:8080."""
    monkeypatch.delenv("CHAT_CONSOLE_URL", raising=False)
    resp = await client.get("/agents-console")
    body = await resp.text()
    assert 'href="http://localhost:8080"' in body


async def test_list_agents_empty(tmp_path: Path):
    """An empty specs root returns []."""
    app = web.Application()
    register_routes(
        app,
        db_path=tmp_path / "agents.sqlite",
        specs_root=tmp_path / "empty-specs",
    )
    async with TestServer(app) as server, TestClient(server) as c:
        resp = await c.get("/agents")
        assert resp.status == 200
        assert await resp.json() == []


async def test_list_agents_returns_summaries(client: TestClient, specs_root: Path):
    _write_spec(specs_root, "second")
    resp = await client.get("/agents")
    assert resp.status == 200
    body = await resp.json()
    names = sorted(s["name"] for s in body)
    assert names == ["hello-world", "second"]
    # Each entry has the expected summary keys
    for s in body:
        assert "spec_hash" in s
        assert "model" in s
        assert "fork" in s
        # Phase 6: provider drives the UI chip rendering
        assert "provider" in s


async def test_get_agent_hits(client: TestClient):
    resp = await client.get("/agents/hello-world")
    assert resp.status == 200
    body = await resp.json()
    assert body["name"] == "hello-world"
    assert "system_prompt" in body
    assert body["fork"] == "dev"


async def test_get_agent_misses(client: TestClient):
    resp = await client.get("/agents/ghost")
    assert resp.status == 404


# ---------- POST /agents/{name}/run ----------


async def test_spawn_run_returns_202_with_run_id(client: TestClient):
    resp = await client.post(
        "/agents/hello-world/run", json={"prompt": "hi"}
    )
    assert resp.status == 202
    body = await resp.json()
    assert "run_id" in body
    assert body["agent"] == "hello-world"
    assert body["status"] in ("pending", "running")


async def test_spawn_run_unknown_agent_404(client: TestClient):
    resp = await client.post("/agents/ghost/run", json={"prompt": "hi"})
    assert resp.status == 404


async def test_spawn_run_empty_prompt_400(client: TestClient):
    resp = await client.post("/agents/hello-world/run", json={"prompt": ""})
    assert resp.status == 400


async def test_spawn_run_threads_session_and_turn(client: TestClient):
    resp = await client.post(
        "/agents/hello-world/run",
        json={
            "prompt": "hi",
            "session_id": "sess-X",
            "turn_id": "turn-Y",
        },
    )
    assert resp.status == 202
    run_id = (await resp.json())["run_id"]
    # Pull the row directly from the store to confirm threading
    store = client.app[STORE_KEY]
    row = store.get_run(run_id)
    assert row.parent_session_id == "sess-X"
    assert row.parent_turn_id == "turn-Y"


# ---------- /runs ----------


async def test_list_runs_empty(client: TestClient):
    resp = await client.get("/runs")
    assert resp.status == 200
    assert await resp.json() == []


async def test_list_runs_returns_dicts(client: TestClient):
    # spawn two
    await client.post("/agents/hello-world/run", json={"prompt": "p1"})
    await client.post("/agents/hello-world/run", json={"prompt": "p2"})

    resp = await client.get("/runs")
    body = await resp.json()
    assert len(body) == 2
    for r in body:
        assert "run_id" in r
        assert "agent_name" in r
        assert "status" in r


async def test_list_runs_filtered_by_agent(client: TestClient, specs_root: Path):
    _write_spec(specs_root, "second")
    await client.post("/agents/hello-world/run", json={"prompt": "p1"})
    await client.post("/agents/second/run", json={"prompt": "p2"})

    resp = await client.get("/runs?agent=second")
    body = await resp.json()
    assert len(body) == 1
    assert body[0]["agent_name"] == "second"


async def test_list_runs_invalid_limit_400(client: TestClient):
    resp = await client.get("/runs?limit=not-a-number")
    assert resp.status == 400


async def test_get_run_unknown_404(client: TestClient):
    resp = await client.get("/runs/does-not-exist")
    assert resp.status == 404


async def test_get_run_returns_full_dict(client: TestClient):
    spawn = await client.post(
        "/agents/hello-world/run", json={"prompt": "hi"}
    )
    run_id = (await spawn.json())["run_id"]
    resp = await client.get(f"/runs/{run_id}")
    assert resp.status == 200
    body = await resp.json()
    assert body["run_id"] == run_id
    assert body["agent_name"] == "hello-world"
    assert body["fork"] == "dev"
    assert body["pid"] == 99999  # fake_spawn's pid


# ---------- SSE /runs/{id}/stream ----------


def _parse_sse(raw: bytes) -> list[dict]:
    """Pull `data: {json}` payloads out of an SSE response body."""
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


async def test_stream_unknown_run_404(client: TestClient):
    resp = await client.get("/runs/does-not-exist/stream")
    assert resp.status == 404


async def test_stream_replays_completed_run(client: TestClient):
    """Pre-populate a finished run with events + manually mark done; the
    SSE endpoint should replay then emit a status frame."""
    store = client.app[STORE_KEY]
    run = store.create_run(
        agent_name="hello-world",
        spec_hash="h",
        fork="dev",
        prompt="hi",
    )
    store.append_event(run.run_id, "token", {"text": "alpha"})
    store.append_event(run.run_id, "token", {"text": "beta"})
    store.update_status(run.run_id, "done", exit_code=0)

    resp = await client.get(f"/runs/{run.run_id}/stream")
    assert resp.status == 200
    raw = await resp.read()
    frames = _parse_sse(raw)
    # Two data frames (the events) plus the status frame at the tail
    tokens = [
        f["data"]["text"] for f in frames if f.get("type") == "token"
    ]
    assert tokens == ["alpha", "beta"]
    assert b"event: status" in raw
    assert b'"status":"done"' in raw


async def test_stream_resumes_from_offset(client: TestClient):
    store = client.app[STORE_KEY]
    run = store.create_run(
        agent_name="hello-world", spec_hash="h", fork="dev", prompt="hi",
    )
    for i in range(5):
        store.append_event(run.run_id, "token", {"text": str(i)})
    store.update_status(run.run_id, "done", exit_code=0)

    resp = await client.get(f"/runs/{run.run_id}/stream", params={"from": 3})
    raw = await resp.read()
    frames = _parse_sse(raw)
    tokens = [f["data"]["text"] for f in frames if f.get("type") == "token"]
    assert tokens == ["3", "4"]


async def test_stream_invalid_from_400(client: TestClient):
    store = client.app[STORE_KEY]
    run = store.create_run(
        agent_name="hello-world", spec_hash="h", fork="dev", prompt="hi",
    )
    resp = await client.get(f"/runs/{run.run_id}/stream?from=not-a-number")
    assert resp.status == 400


# ---------- POST /runs/{id}/cancel ----------


async def test_cancel_run_pending_succeeds(client: TestClient):
    spawn = await client.post(
        "/agents/hello-world/run", json={"prompt": "hi"}
    )
    run_id = (await spawn.json())["run_id"]
    # Run is pending; daemon never actually started since spawn_fn is fake
    resp = await client.post(f"/runs/{run_id}/cancel")
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "cancelled"

    # Verify persisted
    store = client.app[STORE_KEY]
    fetched = store.get_run(run_id)
    assert fetched.status == "cancelled"


async def test_cancel_run_already_done_400(client: TestClient):
    store = client.app[STORE_KEY]
    run = store.create_run(
        agent_name="hello-world", spec_hash="h", fork="dev", prompt="hi",
    )
    store.update_status(run.run_id, "done", exit_code=0)
    resp = await client.post(f"/runs/{run.run_id}/cancel")
    assert resp.status == 400


# ---------- Phase 4: requires_approval gating + /approvals routes ----------


def _write_approval_spec(root: Path, name: str = "approval-needed") -> Path:
    p = root / f"{name}.md"
    p.write_text(
        "---\nfork: dev\nmodel: sonnet\nrequires_approval: true\n---\nbody"
    )
    return p


async def test_spawn_gated_run_starts_awaiting_approval(client: TestClient, specs_root: Path):
    _write_approval_spec(specs_root, "approval-needed")
    resp = await client.post(
        "/agents/approval-needed/run", json={"prompt": "do thing"}
    )
    assert resp.status == 202
    body = await resp.json()
    assert body["status"] == "awaiting_approval"

    # Run row exists in awaiting_approval; pid is None (daemon not launched)
    store = client.app[STORE_KEY]
    fetched = store.get_run(body["run_id"])
    assert fetched.status == "awaiting_approval"
    assert fetched.pid is None


async def test_spawn_ungated_run_unchanged(client: TestClient):
    """Without requires_approval, spawn flow is the Phase-1 path."""
    resp = await client.post("/agents/hello-world/run", json={"prompt": "p"})
    body = await resp.json()
    assert body["status"] in ("pending", "running")
    fetched = client.app[STORE_KEY].get_run(body["run_id"])
    assert fetched.pid is not None  # FakeProc pid


async def test_list_approvals_returns_awaiting(client: TestClient, specs_root: Path):
    _write_approval_spec(specs_root, "needs-approval")
    # Spawn a gated run and an ungated one
    await client.post("/agents/needs-approval/run", json={"prompt": "p1"})
    await client.post("/agents/hello-world/run", json={"prompt": "p2"})

    resp = await client.get("/approvals")
    body = await resp.json()
    assert len(body) == 1
    assert body[0]["status"] == "awaiting_approval"
    assert body[0]["agent_name"] == "needs-approval"


async def test_approve_run_launches_daemon(client: TestClient, specs_root: Path):
    _write_approval_spec(specs_root)
    spawn = await client.post("/agents/approval-needed/run", json={"prompt": "p"})
    run_id = (await spawn.json())["run_id"]

    resp = await client.post(
        f"/runs/{run_id}/approve",
        json={"approver": "[ENTERPRISE: maintainer id]", "reason": "looks fine"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "pending"
    assert body["pid"] == 99999  # FakeProc pid

    fetched = client.app[STORE_KEY].get_run(run_id)
    assert fetched.status == "pending"
    assert fetched.pid == 99999


async def test_approve_run_audits_decision(client: TestClient, specs_root: Path, tmp_path: Path):
    _write_approval_spec(specs_root)
    spawn = await client.post("/agents/approval-needed/run", json={"prompt": "p"})
    run_id = (await spawn.json())["run_id"]

    await client.post(
        f"/runs/{run_id}/approve",
        json={"approver": "[ENTERPRISE: maintainer id]", "reason": "ok to proceed"},
    )

    audit = client.app[AUDIT_KEY]
    records = audit.read_all()
    decision_records = [r for r in records if r["event"] == "approval_decision"]
    assert len(decision_records) == 1
    assert decision_records[0]["decision"] == "approve"
    assert decision_records[0]["approver"] == "[ENTERPRISE: maintainer id]"
    assert decision_records[0]["run_id"] == run_id


async def test_approve_run_already_pending_400(client: TestClient):
    """Can't approve a run that's not awaiting approval."""
    spawn = await client.post("/agents/hello-world/run", json={"prompt": "p"})
    run_id = (await spawn.json())["run_id"]
    resp = await client.post(f"/runs/{run_id}/approve", json={"approver": "x"})
    assert resp.status == 400


async def test_approve_run_unknown_404(client: TestClient):
    resp = await client.post("/runs/does-not-exist/approve", json={"approver": "x"})
    assert resp.status == 404


async def test_deny_run_flips_to_cancelled(client: TestClient, specs_root: Path):
    _write_approval_spec(specs_root)
    spawn = await client.post("/agents/approval-needed/run", json={"prompt": "p"})
    run_id = (await spawn.json())["run_id"]

    resp = await client.post(
        f"/runs/{run_id}/deny",
        json={"approver": "[ENTERPRISE: maintainer id]", "reason": "scope creep"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "cancelled"

    fetched = client.app[STORE_KEY].get_run(run_id)
    assert fetched.status == "cancelled"
    assert "scope creep" in fetched.error


async def test_deny_audits_decision(client: TestClient, specs_root: Path):
    _write_approval_spec(specs_root)
    spawn = await client.post("/agents/approval-needed/run", json={"prompt": "p"})
    run_id = (await spawn.json())["run_id"]

    await client.post(
        f"/runs/{run_id}/deny",
        json={"approver": "[ENTERPRISE: maintainer id]", "reason": "out of scope"},
    )
    audit = client.app[AUDIT_KEY]
    decisions = [r for r in audit.read_all() if r["event"] == "approval_decision"]
    assert decisions[-1]["decision"] == "deny"
    assert decisions[-1]["reason"] == "out of scope"


async def test_deny_already_done_400(client: TestClient):
    spawn = await client.post("/agents/hello-world/run", json={"prompt": "p"})
    run_id = (await spawn.json())["run_id"]
    # Status is pending (not awaiting_approval) — deny should refuse
    resp = await client.post(f"/runs/{run_id}/deny", json={"approver": "x", "reason": "no"})
    assert resp.status == 400


async def test_deny_unknown_404(client: TestClient):
    resp = await client.post("/runs/ghost/deny", json={"approver": "x", "reason": "no"})
    assert resp.status == 404


async def test_infraops_fork_auto_requires_approval(client: TestClient, specs_root: Path):
    """Phase 5: spec.fork=infraops auto-forces requires_approval=True even
    when the spec doesn't set the field. The security boundary for ops
    runs is the approval gate."""
    p = specs_root / "ops-task.md"
    p.write_text("---\nfork: infraops\nmodel: sonnet\n---\nbody")
    resp = await client.post("/agents/ops-task/run", json={"prompt": "p"})
    body = await resp.json()
    assert body["status"] == "awaiting_approval"

    fetched = client.app[STORE_KEY].get_run(body["run_id"])
    assert fetched.fork == "infraops"
    assert fetched.status == "awaiting_approval"


async def test_infraops_audit_records_fork_policy_source(client: TestClient, specs_root: Path):
    """When fork policy (not spec) drives requires_approval, the audit
    record's requires_approval_source field reflects that."""
    p = specs_root / "ops-implicit.md"
    p.write_text("---\nfork: infraops\nmodel: sonnet\n---\nbody")
    spawn = await client.post("/agents/ops-implicit/run", json={"prompt": "p"})
    run_id = (await spawn.json())["run_id"]

    audit = client.app[AUDIT_KEY]
    spawn_records = [
        r for r in audit.read_all()
        if r["event"] == "run_spawned" and r["run_id"] == run_id
    ]
    assert len(spawn_records) == 1
    assert spawn_records[0]["requires_approval_source"] == "fork-policy"


async def test_spec_explicit_approval_audit_source_is_spec(client: TestClient, specs_root: Path):
    """When the spec itself sets requires_approval, audit reflects spec source."""
    p = specs_root / "spec-explicit.md"
    p.write_text(
        "---\nfork: dev\nmodel: sonnet\nrequires_approval: true\n---\nbody"
    )
    spawn = await client.post("/agents/spec-explicit/run", json={"prompt": "p"})
    run_id = (await spawn.json())["run_id"]

    audit = client.app[AUDIT_KEY]
    spawn_records = [
        r for r in audit.read_all()
        if r["event"] == "run_spawned" and r["run_id"] == run_id
    ]
    assert spawn_records[0]["requires_approval_source"] == "spec"


async def test_spawn_audit_records_run_spawned(client: TestClient, specs_root: Path):
    _write_approval_spec(specs_root, "auditspec")
    spawn = await client.post("/agents/auditspec/run", json={"prompt": "p"})
    run_id = (await spawn.json())["run_id"]
    audit = client.app[AUDIT_KEY]
    spawn_records = [r for r in audit.read_all() if r["event"] == "run_spawned"]
    matching = [r for r in spawn_records if r["run_id"] == run_id]
    assert len(matching) == 1
    assert matching[0]["agent_name"] == "auditspec"
    assert matching[0]["requires_approval"] is True


async def test_cancel_run_unknown_404(client: TestClient):
    resp = await client.post("/runs/does-not-exist/cancel")
    assert resp.status == 404


# ---------- /services (Phase 7) ----------


def _write_service(root: Path, name: str, unit: str, purpose: str = "x") -> None:
    p = root / f"{name}.md"
    p.write_text(
        f"---\nkind: service\nunit: {unit}\npurpose: {purpose}\n---\nbody"
    )


async def _fake_status(unit: str, scope: str = "user") -> dict:
    """Pretend systemctl: anything ending .timer is 'waiting'; ghosts unknown."""
    if "ghost" in unit:
        return {
            "active_state": "unknown", "sub_state": None, "main_pid": None,
            "memory_bytes": None, "started_at": None, "result": None,
        }
    sub = "waiting" if unit.endswith(".timer") else "running"
    return {
        "active_state": "active", "sub_state": sub, "main_pid": 1234,
        "memory_bytes": 67108864, "started_at": "Thu 2026-05-07 10:00:00 CDT",
        "result": "success",
    }


async def _fake_logs(unit: str, scope: str = "user", n: int = 30) -> list[str]:
    return [f"line-1-{unit}", f"line-2-{unit}"]


@pytest.fixture
async def services_client(tmp_path: Path, monkeypatch):
    """A TestClient with two service specs and stubbed status/logs."""
    specs = tmp_path / "specs"
    specs.mkdir()
    _write_service(specs, "console", "console.service", "agents-console control surface")
    _write_service(specs, "backup-timer", "backup.timer", "nightly backup")

    from means.agents.routes import services_module
    monkeypatch.setattr(services_module, "query_status", _fake_status)
    monkeypatch.setattr(services_module, "query_logs", _fake_logs)

    app = web.Application()
    register_routes(
        app,
        db_path=tmp_path / "agents.sqlite",
        specs_root=specs,
        spawn_fn=_fake_spawn,
        audit_path=tmp_path / "audit.jsonl",
    )
    async with TestServer(app) as server, TestClient(server) as c:
        yield c


async def test_list_services_returns_specs_with_status(services_client: TestClient):
    resp = await services_client.get("/services")
    assert resp.status == 200
    body = await resp.json()
    names = sorted(s["name"] for s in body)
    assert names == ["backup-timer", "console"]
    for s in body:
        assert s["kind"] == "service"
        assert "unit" in s
        assert "status" in s
        assert s["status"]["active_state"] == "active"


async def test_list_services_timer_substate(services_client: TestClient):
    """Timer units report sub_state=waiting (oneshot) — UI uses this to
    choose the right idle visualization."""
    resp = await services_client.get("/services")
    body = await resp.json()
    timer = next(s for s in body if s["name"] == "backup-timer")
    assert timer["status"]["sub_state"] == "waiting"


async def test_get_service_returns_logs_and_description(services_client: TestClient):
    resp = await services_client.get("/services/console")
    assert resp.status == 200
    body = await resp.json()
    assert body["unit"] == "console.service"
    assert body["description"] == "body"
    assert body["status"]["active_state"] == "active"
    assert body["logs"] == ["line-1-console.service", "line-2-console.service"]


async def test_get_service_unknown_404(services_client: TestClient):
    resp = await services_client.get("/services/ghost")
    assert resp.status == 404


async def test_list_services_empty_when_no_service_specs(tmp_path: Path):
    """A specs root with only agent files → /services returns []."""
    specs = tmp_path / "specs"
    specs.mkdir()
    _write_spec(specs, "hello-world")  # agent, not a service
    app = web.Application()
    register_routes(
        app,
        db_path=tmp_path / "agents.sqlite",
        specs_root=specs,
        spawn_fn=_fake_spawn,
        audit_path=tmp_path / "audit.jsonl",
    )
    async with TestServer(app) as server, TestClient(server) as c:
        resp = await c.get("/services")
        assert await resp.json() == []


async def test_agents_endpoint_does_not_include_service_specs(services_client: TestClient):
    """Existing /agents listing must not leak service specs in."""
    resp = await services_client.get("/agents")
    body = await resp.json()
    assert body == []  # only services, no agents in this fixture


# ---------- /workflows (Phase 8) ----------


def _write_workflow_spec(root: Path, name: str, content: str) -> None:
    p = root / f"{name}.md"
    p.write_text(content)


@pytest.fixture
async def workflows_client(tmp_path: Path):
    """A TestClient with a workflow spec mounted; spawn_fn is a no-op fake."""
    specs = tmp_path / "specs"
    specs.mkdir()
    # Need an agent the workflow references so it parses
    _write_spec(specs, "step-a")
    _write_workflow_spec(specs, "demo", (
        "---\nkind: workflow\nsteps:\n"
        "  - id: a\n    agent: step-a\n    prompt: \"hi: {input}\"\n"
        "---\nworkflow body"
    ))
    app = web.Application()
    register_routes(
        app,
        db_path=tmp_path / "agents.sqlite",
        specs_root=specs,
        spawn_fn=_fake_spawn,
        audit_path=tmp_path / "audit.jsonl",
    )
    async with TestServer(app) as server, TestClient(server) as c:
        yield c


async def test_list_workflows(workflows_client: TestClient):
    resp = await workflows_client.get("/workflows")
    assert resp.status == 200
    body = await resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "demo"
    assert body[0]["kind"] == "workflow"
    assert body[0]["step_count"] == 1
    # Listing excludes step bodies (lightweight)
    assert "steps" not in body[0]


async def test_get_workflow_includes_steps(workflows_client: TestClient):
    resp = await workflows_client.get("/workflows/demo")
    assert resp.status == 200
    body = await resp.json()
    assert body["steps"][0]["agent"] == "step-a"
    assert body["steps"][0]["prompt"] == "hi: {input}"


async def test_get_workflow_unknown_404(workflows_client: TestClient):
    resp = await workflows_client.get("/workflows/ghost")
    assert resp.status == 404


async def test_spawn_workflow_creates_pending_row(workflows_client: TestClient):
    resp = await workflows_client.post(
        "/workflows/demo/run",
        json={"prompt": "initial input"},
    )
    assert resp.status == 202
    body = await resp.json()
    assert "workflow_run_id" in body
    assert body["workflow"] == "demo"
    assert body["status"] == "pending"

    # Workflow run row exists in store
    store = workflows_client.app[STORE_KEY]
    wr = store.get_workflow_run(body["workflow_run_id"])
    assert wr is not None
    assert wr.workflow_name == "demo"
    assert wr.prompt == "initial input"


async def test_spawn_workflow_missing_prompt_400(workflows_client: TestClient):
    resp = await workflows_client.post("/workflows/demo/run", json={})
    assert resp.status == 400


async def test_spawn_workflow_unknown_404(workflows_client: TestClient):
    resp = await workflows_client.post(
        "/workflows/ghost/run", json={"prompt": "x"}
    )
    assert resp.status == 404


async def test_list_workflow_runs(workflows_client: TestClient):
    """Spawn two workflows; list returns most-recent first."""
    r1 = await workflows_client.post(
        "/workflows/demo/run", json={"prompt": "first"}
    )
    rid1 = (await r1.json())["workflow_run_id"]
    r2 = await workflows_client.post(
        "/workflows/demo/run", json={"prompt": "second"}
    )
    rid2 = (await r2.json())["workflow_run_id"]
    resp = await workflows_client.get("/workflow-runs")
    body = await resp.json()
    assert len(body) == 2
    assert body[0]["workflow_run_id"] == rid2  # newer first
    assert body[1]["workflow_run_id"] == rid1


async def test_get_workflow_run_includes_step_runs(workflows_client: TestClient):
    """A workflow run's detail endpoint enumerates child agent runs."""
    spawn_resp = await workflows_client.post(
        "/workflows/demo/run", json={"prompt": "x"}
    )
    workflow_run_id = (await spawn_resp.json())["workflow_run_id"]

    # Manually insert a child agent run linked to this workflow
    store = workflows_client.app[STORE_KEY]
    store.create_run(
        agent_name="step-a", spec_hash="h", fork="dev", prompt="rendered prompt",
        parent_workflow_run_id=workflow_run_id,
    )

    resp = await workflows_client.get(f"/workflow-runs/{workflow_run_id}")
    body = await resp.json()
    assert body["workflow_run_id"] == workflow_run_id
    assert len(body["steps"]) == 1
    assert body["steps"][0]["agent_name"] == "step-a"
    assert body["steps"][0]["parent_workflow_run_id"] == workflow_run_id


async def test_get_workflow_run_unknown_404(workflows_client: TestClient):
    resp = await workflows_client.get("/workflow-runs/ghost-id")
    assert resp.status == 404


async def test_agents_endpoint_does_not_include_workflow_specs(workflows_client: TestClient):
    """Existing /agents listing must not leak workflow specs in."""
    resp = await workflows_client.get("/agents")
    body = await resp.json()
    names = [a["name"] for a in body]
    assert "demo" not in names
    assert names == ["step-a"]


# ---------- /triggers (Phase 9) ----------


def _write_trigger_spec(
    root: Path, name: str, *,
    schedule: str = "*/5 * * * *",
    target_kind: str = "agent",
    target: str = "hello-world",
    prompt: str = "hi",
) -> None:
    p = root / f"{name}.md"
    p.write_text((
        f"---\nkind: trigger\nschedule: \"{schedule}\"\n"
        f"target_kind: {target_kind}\ntarget: {target}\nprompt: {prompt}\n"
        f"---\nbody"
    ))


@pytest.fixture
async def triggers_client(tmp_path: Path):
    """A TestClient with a trigger spec + agent target. Scheduler is
    started by register_routes but the fast tick (30s) never fires
    within a unit-test timescale, so it stays a no-op."""
    specs = tmp_path / "specs"
    specs.mkdir()
    _write_spec(specs, "hello-world")
    _write_trigger_spec(specs, "heartbeat")
    app = web.Application()
    register_routes(
        app,
        db_path=tmp_path / "agents.sqlite",
        specs_root=specs,
        spawn_fn=_fake_spawn,
        audit_path=tmp_path / "audit.jsonl",
    )
    async with TestServer(app) as server, TestClient(server) as c:
        yield c


async def test_list_triggers_merges_state(triggers_client: TestClient):
    resp = await triggers_client.get("/triggers")
    assert resp.status == 200
    body = await resp.json()
    assert len(body) == 1
    t = body[0]
    assert t["name"] == "heartbeat"
    assert t["kind"] == "trigger"
    assert t["last_fired_at"] is None
    assert t["fire_count"] == 0
    assert t["next_fire_at"] is not None  # cron is parseable


async def test_get_trigger_includes_description(triggers_client: TestClient):
    resp = await triggers_client.get("/triggers/heartbeat")
    assert resp.status == 200
    body = await resp.json()
    assert body["description"] == "body"
    assert body["target"] == "hello-world"


async def test_get_trigger_unknown_404(triggers_client: TestClient):
    resp = await triggers_client.get("/triggers/ghost")
    assert resp.status == 404


async def test_fire_trigger_creates_run_with_triggered_by(triggers_client: TestClient):
    resp = await triggers_client.post("/triggers/heartbeat/fire")
    assert resp.status == 202
    body = await resp.json()
    assert body["trigger"] == "heartbeat"
    assert "fired_at" in body

    # The agent run was created
    store = triggers_client.app[STORE_KEY]
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0].agent_name == "hello-world"
    assert runs[0].triggered_by == "heartbeat"

    # State was recorded
    state = store.get_trigger_state("heartbeat")
    assert state is not None
    assert state.fire_count == 1


async def test_fire_trigger_unknown_404(triggers_client: TestClient):
    resp = await triggers_client.post("/triggers/ghost/fire")
    assert resp.status == 404


async def test_agents_endpoint_does_not_include_trigger_specs(triggers_client: TestClient):
    """The /agents listing must not leak trigger specs."""
    resp = await triggers_client.get("/agents")
    body = await resp.json()
    names = [a["name"] for a in body]
    assert "heartbeat" not in names
    assert names == ["hello-world"]
