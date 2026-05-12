"""Detached agent runner. Invoked by Run.spawn() via subprocess.Popen.

  python -m means.agents.runtime.daemon --run-id <id> --db <path>

Reads the run row, loads the spec by name (verifies hash matches the row —
detects spec drift since queue), selects a backend, and runs to completion.
Persists status transitions through RunStore. On any error, status=error
with a captured message + non-zero exit code.

Phase 2: per-run workspace at `data/workspaces/<run_id>/` becomes the
subprocess cwd unless the spec overrides via `cwd:`. The directory is
auto-created (mkdir parents=True, exist_ok=True) before the backend runs.
Cleanup is deferred (Phase 5 GC); for now, sortable run_id makes manual
pruning straightforward.

Phase 6 introduces a backend factory that parses `<provider>:<model>` and
dispatches to API-direct backends for OpenAI / Gemini / Ollama.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Callable

from ..specs.loader import find_spec
from ..specs.model import AgentSpec

from .backend import AgentBackend
from .judge import Judge, LLMJudge
from .gemini_backend import GeminiBackend
from .ollama_backend import OllamaBackend
from .ollama_hosts import load_hosts
from .openai_backend import OpenAIBackend
from .sink import EventSink
from .store import RunStore


_DEFAULT_SPECS_ROOT = Path(__file__).resolve().parent.parent / "specs"
_DEFAULT_WORKSPACE_ROOT = (
    Path(__file__).resolve().parent.parent / "data" / "workspaces"
)


def select_backend(spec: AgentSpec, workspace: Path) -> AgentBackend:
    """Pick a backend based on spec.provider.

    Supported providers (all HTTP API-direct — no CLI subprocess):

      - ollama  → OllamaBackend (NDJSON /api/chat against a named host)
      - openai  → OpenAIBackend (SSE /v1/chat/completions)
      - gemini  → GeminiBackend (SSE :streamGenerateContent)

    The `claude` provider was removed: agents-console is model-agnostic and
    no longer carries a CLI-subscription auth path. Specs that historically
    relied on the bare-model default (`model: sonnet` → provider="claude")
    surface a clean ValueError here; migrate them to
    `model: <provider>:<id>` with one of the supported providers above.

    `workspace` is the per-run sandbox dir (precomputed by run_one). All
    current backends are HTTP-direct and ignore it; spec.cwd is honored
    where the backend opens a subprocess of its own (none do today).
    """
    p = spec.provider
    if p == "claude":
        raise ValueError(
            f"spec {spec.name!r} declares provider='claude'; the claude "
            f"backend was removed (agents-console is model-agnostic). "
            f"Set `model: <provider>:<model-id>` with provider in "
            f"{{ollama, openai, gemini}}."
        )
    if p == "ollama":
        host_alias, sep, model_tag = spec.model_id.partition("/")
        if not sep or not model_tag:
            raise ValueError(
                f"ollama model must be 'ollama:<host-alias>/<model-tag>', "
                f"got spec.model={spec.model!r}"
            )
        return OllamaBackend(
            hosts=load_hosts(), host_alias=host_alias, model_tag=model_tag
        )
    if p == "openai":
        return OpenAIBackend(model=spec.model_id)
    if p == "gemini":
        return GeminiBackend(model=spec.model_id)
    raise ValueError(f"unknown provider {p!r} in spec.model={spec.model!r}")


def _default_judge_factory(spec: AgentSpec) -> Judge:
    """Default judge factory used by run_one. Tests inject their own."""
    return LLMJudge()


async def run_one(
    run_id: str,
    db_path: Path,
    *,
    specs_root: Path = _DEFAULT_SPECS_ROOT,
    workspace_root: Path = _DEFAULT_WORKSPACE_ROOT,
    backend_factory: Callable[[AgentSpec, Path], AgentBackend] = select_backend,
    judge_factory: Callable[[AgentSpec], Judge] = _default_judge_factory,
) -> int:
    """Execute the run identified by `run_id`. Returns the exit code.

    Phase 3: after the backend completes, if the spec declares
    `qa.criteria`, the daemon runs the Judge over the recorded events.
    Outcome 'fail' or 'error' flips the run's final status from 'done'
    to 'error' (with qa_reason captured); 'pass' stays 'done'.
    """
    store = RunStore(db_path)
    run = store.get_run(run_id)
    if run is None:
        sys.stderr.write(f"daemon: run {run_id!r} not found\n")
        return 2

    sink = EventSink(store, run_id)

    try:
        spec = find_spec(specs_root, run.agent_name)
        if spec is None:
            store.update_status(
                run_id, "error",
                error=f"spec not found: {run.agent_name!r}",
                exit_code=2,
            )
            return 2
        if spec.spec_hash != run.spec_hash:
            store.update_status(
                run_id, "error",
                error="spec hash mismatch — spec changed since run was queued",
                exit_code=3,
            )
            return 3

        # Phase 2: per-run workspace dir. Created before the backend touches
        # the filesystem so tools like Write have somewhere to land.
        workspace = workspace_root / run_id
        workspace.mkdir(parents=True, exist_ok=True)

        backend = backend_factory(spec, workspace)
        store.update_status(run_id, "running", pid=os.getpid())
        await backend.run(spec, run.prompt, sink)

        # Phase 3: QA pass. Skipped when spec.qa.criteria is absent.
        qa_criteria = (spec.qa or {}).get("criteria")
        if qa_criteria:
            judge = judge_factory(spec)
            events = store.get_events(run_id)
            result = await judge.judge(spec, run.prompt, events)
            sink.emit("qa_step", {
                "outcome": result.outcome,
                "reason": result.reason,
            })
            if result.outcome == "pass":
                store.update_status(
                    run_id, "done", exit_code=0,
                    qa_outcome="pass", qa_reason=result.reason,
                )
                return 0
            # fail or error → flip to error status
            store.update_status(
                run_id, "error", exit_code=4,
                qa_outcome=result.outcome,
                qa_reason=result.reason,
                error=f"qa {result.outcome}: {result.reason}",
            )
            return 4

        # No QA configured — run completed cleanly
        store.update_status(run_id, "done", exit_code=0)
        return 0
    except Exception as exc:  # pragma: no cover (logged + persisted below)
        logging.exception("daemon: run %s failed", run_id)
        store.update_status(run_id, "error", error=str(exc), exit_code=1)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args()
    code = asyncio.run(run_one(args.run_id, args.db))
    sys.exit(code)


if __name__ == "__main__":
    main()
