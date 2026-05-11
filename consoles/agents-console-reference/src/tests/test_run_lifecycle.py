"""Tests for run.py + daemon.py — spawn flow, backend selection, daemon
run-loop in isolation (no actual subprocess).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from means.agents.runtime.backend import AgentBackend
from means.agents.runtime.claude_cli_backend import ClaudeCliBackend
from means.agents.runtime.daemon import run_one, select_backend
from means.agents.runtime.run import spawn
from means.agents.runtime.store import RunStore
from means.agents.specs.loader import load_spec
from means.agents.specs.model import AgentSpec


# ---------- fixtures ----------


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "agents.sqlite")


@pytest.fixture
def specs_root(tmp_path: Path) -> Path:
    root = tmp_path / "specs"
    root.mkdir()
    return root


def _write_spec(root: Path, name: str, body: str = "you are a helper") -> Path:
    p = root / f"{name}.md"
    p.write_text(f"---\nmodel: claude-sonnet-4-7\nfork: dev\n---\n{body}")
    return p


def _make_spec(model: str, root: Path) -> AgentSpec:
    return AgentSpec(
        name="x", domain="", fork="dev",
        model=model, system_prompt="",
        timeout_s=60, tools=[], qa={}, cwd=None, requires_approval=False,
        spec_path=root / "x.md", spec_hash="h",
    )


# ---------- FakeBackend / FakeProc ----------


class FakeBackend(AgentBackend):
    def __init__(self, *, raise_exc: Optional[Exception] = None):
        self.raise_exc = raise_exc
        self.received: list[tuple[AgentSpec, str]] = []

    async def run(self, spec: AgentSpec, prompt: str, sink) -> None:
        self.received.append((spec, prompt))
        sink.emit("token", {"text": "hello"})
        sink.emit("token", {"text": " world"})
        if self.raise_exc:
            raise self.raise_exc


class FakeProc:
    def __init__(self, pid: int = 99999):
        self.pid = pid
        self.cmd: list[str] = []
        self.cwd: Optional[Path] = None


# ---------- spawn ----------


def test_spawn_creates_pending_row_and_records_pid(store: RunStore):
    captured = []

    def fake_spawn(cmd, cwd):
        proc = FakeProc(pid=12345)
        proc.cmd = cmd
        proc.cwd = cwd
        captured.append(proc)
        return proc

    run = spawn(
        store=store,
        agent_name="hello-world",
        spec_hash="h" * 64,
        fork="dev",
        prompt="hi",
        spawn_fn=fake_spawn,
    )

    assert run.status == "pending"
    fetched = store.get_run(run.run_id)
    assert fetched is not None
    assert fetched.pid == 12345
    assert len(captured) == 1


def test_spawn_invokes_daemon_module(store: RunStore):
    captured = []

    def fake_spawn(cmd, cwd):
        captured.append((cmd, cwd))
        return FakeProc()

    spawn(
        store=store,
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
        spawn_fn=fake_spawn,
    )

    cmd, _cwd = captured[0]
    assert "-m" in cmd
    assert "means.agents.runtime.daemon" in cmd
    assert "--run-id" in cmd
    assert "--db" in cmd
    assert str(store.db_path) in cmd


def test_spawn_passes_parent_chat_threading(store: RunStore):
    proc = FakeProc()
    run = spawn(
        store=store,
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
        parent_session_id="sess-1",
        parent_turn_id="turn-1",
        spawn_fn=lambda cmd, cwd: proc,
    )
    fetched = store.get_run(run.run_id)
    assert fetched.parent_session_id == "sess-1"
    assert fetched.parent_turn_id == "turn-1"


def test_spawn_launch_false_skips_subprocess(store: RunStore):
    """launch=False creates row but doesn't call spawn_fn."""
    captured = []

    def fake_spawn(cmd, cwd):
        captured.append(cmd)
        return FakeProc()

    run = spawn(
        store=store,
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
        spawn_fn=fake_spawn,
        launch=False,
    )
    assert captured == []  # spawn_fn was NOT called
    fetched = store.get_run(run.run_id)
    assert fetched.status == "pending"
    assert fetched.pid is None


def test_spawn_launch_false_with_initial_status(store: RunStore):
    """Phase 4: gated runs start with status=awaiting_approval."""
    run = spawn(
        store=store,
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
        spawn_fn=lambda c, w: FakeProc(),
        launch=False,
        initial_status="awaiting_approval",
    )
    fetched = store.get_run(run.run_id)
    assert fetched.status == "awaiting_approval"
    assert fetched.pid is None


def test_launch_daemon_for_existing_run(store: RunStore):
    """launch_daemon() Popens for an already-created run; sets pid + pending."""
    from means.agents.runtime.run import launch_daemon

    # Create an awaiting_approval row
    run = spawn(
        store=store,
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
        spawn_fn=lambda c, w: FakeProc(),
        launch=False,
        initial_status="awaiting_approval",
    )

    # Now launch
    captured = []
    def fake_spawn(cmd, cwd):
        captured.append(cmd)
        return FakeProc(pid=42)

    pid = launch_daemon(store=store, run_id=run.run_id, spawn_fn=fake_spawn)
    assert pid == 42
    assert len(captured) == 1
    assert "--run-id" in captured[0]
    fetched = store.get_run(run.run_id)
    assert fetched.status == "pending"
    assert fetched.pid == 42


def test_spawn_handles_proc_without_pid(store: RunStore):
    """If spawn_fn returns something without a `.pid`, don't crash."""

    class NoPid:
        pass

    run = spawn(
        store=store,
        agent_name="x", spec_hash="h", fork="dev", prompt="p",
        spawn_fn=lambda cmd, cwd: NoPid(),
    )
    fetched = store.get_run(run.run_id)
    assert fetched.pid is None


# ---------- backend selection ----------


def test_select_backend_returns_claude_cli_for_claude_provider(tmp_path: Path):
    """Phase 6: bare model strings + explicit `claude:` prefix both go to
    ClaudeCliBackend (subprocess `claude -p` — uses [ENTERPRISE: cognitive engine CLI] subscription
    auth, no API key needed)."""
    for model in ("sonnet", "opus", "claude-sonnet-4-6", "claude:haiku"):
        backend = select_backend(_make_spec(model, tmp_path), tmp_path / "ws")
        assert isinstance(backend, ClaudeCliBackend)


def test_select_backend_dispatches_openai(tmp_path: Path, monkeypatch):
    """Phase 6 chunk C: openai provider routes to OpenAIBackend."""
    from means.agents.runtime.openai_backend import OpenAIBackend
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    spec = _make_spec("openai:gpt-4o-mini", tmp_path)
    backend = select_backend(spec, tmp_path / "ws")
    assert isinstance(backend, OpenAIBackend)


def test_select_backend_openai_missing_key_raises(tmp_path: Path, monkeypatch):
    """Missing OPENAI_API_KEY surfaces as RuntimeError at construction."""
    import pytest
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    spec = _make_spec("openai:gpt-4o-mini", tmp_path)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        select_backend(spec, tmp_path / "ws")


def test_select_backend_dispatches_gemini(tmp_path: Path, monkeypatch):
    """Phase 6 chunk D: gemini provider routes to GeminiBackend."""
    from means.agents.runtime.gemini_backend import GeminiBackend
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
    spec = _make_spec("gemini:gemini-2.5-flash", tmp_path)
    backend = select_backend(spec, tmp_path / "ws")
    assert isinstance(backend, GeminiBackend)


def test_select_backend_gemini_missing_key_raises(tmp_path: Path, monkeypatch):
    import pytest
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    spec = _make_spec("gemini:gemini-2.5-flash", tmp_path)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        select_backend(spec, tmp_path / "ws")


def test_select_backend_dispatches_ollama(tmp_path: Path, monkeypatch):
    """Phase 6 chunk B: ollama provider routes to OllamaBackend. Override
    load_hosts so the test isn't tied to the shipped data file."""
    from means.agents.runtime import daemon as daemon_module
    from means.agents.runtime.ollama_backend import OllamaBackend

    monkeypatch.setattr(
        daemon_module, "load_hosts",
        lambda: {"peakai": "http://x:11434"},
    )
    spec = _make_spec("ollama:peakai/qwen3:14b", tmp_path)
    backend = select_backend(spec, tmp_path / "ws")
    assert isinstance(backend, OllamaBackend)


def test_select_backend_ollama_missing_slash_raises(tmp_path: Path):
    """`ollama:qwen3:14b` (no `/`) is malformed — must include host alias."""
    import pytest
    spec = _make_spec("ollama:qwen3:14b", tmp_path)
    with pytest.raises(ValueError, match="host-alias"):
        select_backend(spec, tmp_path / "ws")


def test_select_backend_unknown_provider_raises_value_error(tmp_path: Path):
    """Unknown providers (typos, future names) raise ValueError so the
    daemon writes a clean error rather than guessing."""
    import pytest
    spec = _make_spec("madeup:foo", tmp_path)
    with pytest.raises(ValueError, match="madeup"):
        select_backend(spec, tmp_path / "ws")


# ---------- daemon run_one (in-process, no subprocess) ----------


async def test_run_one_happy_path(store: RunStore, specs_root: Path):
    spec_path = _write_spec(specs_root, "hello-world")
    spec = load_spec(spec_path, root=specs_root)
    run = store.create_run(
        agent_name="hello-world",
        spec_hash=spec.spec_hash,
        fork="dev",
        prompt="hi",
    )

    fake = FakeBackend()
    code = await run_one(
        run.run_id, store.db_path,
        specs_root=specs_root,
        backend_factory=lambda s, w: fake,
    )

    assert code == 0
    fetched = store.get_run(run.run_id)
    assert fetched.status == "done"
    assert fetched.exit_code == 0
    assert fetched.completed_at is not None

    assert len(fake.received) == 1
    received_spec, received_prompt = fake.received[0]
    assert received_spec.name == "hello-world"
    assert received_prompt == "hi"

    events = store.get_events(run.run_id)
    types = [e.type for e in events]
    assert "token" in types


async def test_run_one_unknown_run_returns_2(store: RunStore, specs_root: Path):
    code = await run_one(
        "does-not-exist", store.db_path,
        specs_root=specs_root,
    )
    assert code == 2


async def test_run_one_spec_not_found(store: RunStore, specs_root: Path):
    run = store.create_run(
        agent_name="missing", spec_hash="any", fork="dev", prompt="p",
    )
    code = await run_one(
        run.run_id, store.db_path,
        specs_root=specs_root,
    )
    assert code == 2
    fetched = store.get_run(run.run_id)
    assert fetched.status == "error"
    assert "spec not found" in fetched.error


async def test_run_one_spec_hash_mismatch(store: RunStore, specs_root: Path):
    _write_spec(specs_root, "hello-world")
    run = store.create_run(
        agent_name="hello-world",
        spec_hash="wrong-hash",
        fork="dev",
        prompt="p",
    )
    code = await run_one(
        run.run_id, store.db_path,
        specs_root=specs_root,
    )
    assert code == 3
    fetched = store.get_run(run.run_id)
    assert fetched.status == "error"
    assert "hash mismatch" in fetched.error


async def test_run_one_backend_raises_records_error(
    store: RunStore, specs_root: Path
):
    spec_path = _write_spec(specs_root, "hello-world")
    spec = load_spec(spec_path, root=specs_root)
    run = store.create_run(
        agent_name="hello-world",
        spec_hash=spec.spec_hash,
        fork="dev",
        prompt="p",
    )

    fake = FakeBackend(raise_exc=RuntimeError("provider down"))
    code = await run_one(
        run.run_id, store.db_path,
        specs_root=specs_root,
        backend_factory=lambda s, w: fake,
    )
    assert code == 1
    fetched = store.get_run(run.run_id)
    assert fetched.status == "error"
    assert "provider down" in fetched.error
    assert fetched.exit_code == 1


async def test_run_one_creates_workspace_dir(
    store: RunStore, specs_root: Path, tmp_path: Path
):
    """Daemon creates per-run workspace dir before backend.run."""
    spec_path = _write_spec(specs_root, "hello-world")
    spec = load_spec(spec_path, root=specs_root)
    run = store.create_run(
        agent_name="hello-world",
        spec_hash=spec.spec_hash,
        fork="dev",
        prompt="hi",
    )

    captured_workspaces: list[Path] = []

    def factory(spec, workspace):
        captured_workspaces.append(workspace)
        return FakeBackend()

    workspace_root = tmp_path / "wsroot"
    await run_one(
        run.run_id, store.db_path,
        specs_root=specs_root,
        workspace_root=workspace_root,
        backend_factory=factory,
    )

    assert len(captured_workspaces) == 1
    ws = captured_workspaces[0]
    assert ws == workspace_root / run.run_id
    assert ws.is_dir()


async def test_run_one_qa_pass_keeps_status_done(
    store: RunStore, specs_root: Path
):
    """Spec with qa.criteria and a Judge returning pass → status=done,
    qa_outcome=pass, qa_reason captured."""
    p = specs_root / "qa-pass.md"
    p.write_text(
        "---\nfork: dev\nmodel: sonnet\nqa: {criteria: 'Reply must be concise.'}\n---\nbe terse"
    )
    spec = load_spec(p, root=specs_root)
    run = store.create_run(
        agent_name="qa-pass", spec_hash=spec.spec_hash,
        fork="dev", prompt="hi",
    )

    from means.agents.runtime.judge import Judge, JudgeResult

    class PassJudge(Judge):
        async def judge(self, spec, prompt, events):
            return JudgeResult("pass", "under 50 words")

    code = await run_one(
        run.run_id, store.db_path,
        specs_root=specs_root,
        backend_factory=lambda s, w: FakeBackend(),
        judge_factory=lambda s: PassJudge(),
    )
    assert code == 0
    fetched = store.get_run(run.run_id)
    assert fetched.status == "done"
    assert fetched.qa_outcome == "pass"
    assert fetched.qa_reason == "under 50 words"

    # qa_step event landed in the event log
    events = store.get_events(run.run_id)
    qa_steps = [e for e in events if e.type == "qa_step"]
    assert len(qa_steps) == 1
    assert qa_steps[0].data["outcome"] == "pass"


async def test_run_one_qa_fail_flips_status_to_error(
    store: RunStore, specs_root: Path
):
    """Judge returning fail → status flips from done to error; qa_reason
    surfaces in the run's error field."""
    p = specs_root / "qa-fail.md"
    p.write_text(
        "---\nfork: dev\nmodel: sonnet\nqa: {criteria: 'Must mention bananas.'}\n---\n..."
    )
    spec = load_spec(p, root=specs_root)
    run = store.create_run(
        agent_name="qa-fail", spec_hash=spec.spec_hash,
        fork="dev", prompt="describe an apple",
    )

    from means.agents.runtime.judge import Judge, JudgeResult

    class FailJudge(Judge):
        async def judge(self, spec, prompt, events):
            return JudgeResult("fail", "no banana mentioned")

    code = await run_one(
        run.run_id, store.db_path,
        specs_root=specs_root,
        backend_factory=lambda s, w: FakeBackend(),
        judge_factory=lambda s: FailJudge(),
    )
    assert code == 4
    fetched = store.get_run(run.run_id)
    assert fetched.status == "error"
    assert fetched.exit_code == 4
    assert fetched.qa_outcome == "fail"
    assert fetched.qa_reason == "no banana mentioned"
    assert "qa fail" in fetched.error.lower()
    assert "no banana" in fetched.error


async def test_run_one_qa_judge_error_treated_as_failure(
    store: RunStore, specs_root: Path
):
    """Judge returning outcome=error (e.g. unparseable response) is treated
    as a run failure too — better safe than silently passing."""
    p = specs_root / "qa-buggy.md"
    p.write_text(
        "---\nfork: dev\nmodel: sonnet\nqa: {criteria: 'x'}\n---\n..."
    )
    spec = load_spec(p, root=specs_root)
    run = store.create_run(
        agent_name="qa-buggy", spec_hash=spec.spec_hash, fork="dev", prompt="p",
    )

    from means.agents.runtime.judge import Judge, JudgeResult

    class BrokenJudge(Judge):
        async def judge(self, spec, prompt, events):
            return JudgeResult("error", "unparseable judge response")

    code = await run_one(
        run.run_id, store.db_path,
        specs_root=specs_root,
        backend_factory=lambda s, w: FakeBackend(),
        judge_factory=lambda s: BrokenJudge(),
    )
    assert code == 4
    fetched = store.get_run(run.run_id)
    assert fetched.status == "error"
    assert fetched.qa_outcome == "error"


async def test_run_one_no_qa_criteria_skips_judge(
    store: RunStore, specs_root: Path
):
    """No qa.criteria in spec → judge factory not called; status=done as
    pre-Phase-3."""
    p = specs_root / "no-qa.md"
    p.write_text("---\nfork: dev\nmodel: sonnet\n---\nbody")  # no qa block
    spec = load_spec(p, root=specs_root)
    run = store.create_run(
        agent_name="no-qa", spec_hash=spec.spec_hash, fork="dev", prompt="p",
    )

    judge_called = []

    def factory(spec):
        judge_called.append(spec)
        from means.agents.runtime.judge import Judge

        class _Stub(Judge):
            async def judge(self, *a, **kw):
                raise AssertionError("judge must NOT be invoked when no criteria")
        return _Stub()

    code = await run_one(
        run.run_id, store.db_path,
        specs_root=specs_root,
        backend_factory=lambda s, w: FakeBackend(),
        judge_factory=factory,
    )
    assert code == 0
    fetched = store.get_run(run.run_id)
    assert fetched.status == "done"
    assert fetched.qa_outcome is None
    assert fetched.qa_reason is None
    # judge_factory may have been called (since qa dict is empty), but the
    # stub.judge would have raised. We're verifying the daemon never reached
    # the judge invocation.


async def test_run_one_records_pid_on_running(
    store: RunStore, specs_root: Path
):
    spec_path = _write_spec(specs_root, "hello-world")
    spec = load_spec(spec_path, root=specs_root)
    run = store.create_run(
        agent_name="hello-world",
        spec_hash=spec.spec_hash,
        fork="dev",
        prompt="hi",
    )

    fake = FakeBackend()
    await run_one(
        run.run_id, store.db_path,
        specs_root=specs_root,
        backend_factory=lambda s, w: fake,
    )

    fetched = store.get_run(run.run_id)
    # The daemon's own PID was recorded when it transitioned to running
    assert fetched.pid is not None
    assert fetched.pid > 0
