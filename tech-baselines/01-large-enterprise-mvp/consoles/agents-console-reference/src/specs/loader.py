"""Parse markdown + YAML-frontmatter agent specs into AgentSpec objects.

  ---
  fork: dev
  model: claude-sonnet-4-7
  timeout_s: 120
  ---
  System prompt body...

`name` derives from the file stem; `domain` derives from the relative
subdirectory under the specs root. `spec_hash` is sha256 of the raw file
bytes — stable per file, sensitive to any edit (whitespace included), so
runs that ran against a different version of the prompt are distinguishable
in the audit log.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import yaml

from .model import AgentSpec, ServiceSpec, TriggerSpec, WorkflowSpec, WorkflowStep


_REQUIRED_FIELDS = ("model",)
_VALID_FORKS = ("dev", "infraops")
_VALID_SCOPES = ("user", "system")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_str). ({}, text) if no frontmatter.

    Raises ValueError if the frontmatter parses as a non-mapping (e.g. a list).
    """
    if not text.startswith("---\n"):
        return {}, text
    try:
        # Search from position 3 (the opener's trailing \n) so an empty
        # frontmatter like `---\n---\nbody` also matches.
        end = text.index("\n---\n", 3)
    except ValueError:
        # Unclosed frontmatter — treat as no frontmatter, leave text intact
        return {}, text
    fm_text = text[4:end]
    body = text[end + len("\n---\n"):]
    fm = yaml.safe_load(fm_text) or {}
    if not isinstance(fm, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    return fm, body


def load_spec(path: Path, *, root: Path) -> AgentSpec:
    """Parse a single spec file.

    `root` is the specs directory; used to derive `domain` from the file's
    relative path. `path` may be absolute or relative; both are normalized.
    """
    path = path.resolve()
    root = root.resolve()
    raw = path.read_bytes()
    spec_hash = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    fm, body = parse_frontmatter(text)

    # Phase 7: service specs share the .md format but aren't agents. Reject
    # them here so list_specs's silent-skip catches them and they don't
    # appear in the agents listing. load_service_spec() is the right entry
    # point for kind=service.
    if fm.get("kind") == "service":
        raise ValueError(f"{path}: kind=service — use load_service_spec instead")
    if fm.get("kind") == "workflow":
        raise ValueError(f"{path}: kind=workflow — use load_workflow_spec instead")
    if fm.get("kind") == "trigger":
        raise ValueError(f"{path}: kind=trigger — use load_trigger_spec instead")

    missing = [f for f in _REQUIRED_FIELDS if f not in fm]
    if missing:
        raise ValueError(f"{path}: missing required field(s): {missing}")

    fork = fm.get("fork", "dev")
    if fork not in _VALID_FORKS:
        raise ValueError(
            f"{path}: fork must be one of {_VALID_FORKS}, got {fork!r}"
        )

    rel_parent = path.relative_to(root).parent
    domain = "" if rel_parent == Path(".") else str(rel_parent)

    # Phase 2: distinguish tools-missing from tools-empty so fork defaults
    # only kick in when the spec was silent (resolve_tools handles that).
    if "tools" in fm and fm["tools"] is not None:
        tools: Optional[list[str]] = list(fm["tools"])
    else:
        tools = None

    cwd_raw = fm.get("cwd")
    cwd = str(cwd_raw) if cwd_raw is not None else None

    requires_approval = bool(fm.get("requires_approval", False))

    return AgentSpec(
        name=path.stem,
        domain=domain,
        fork=fork,
        model=str(fm["model"]),
        system_prompt=body.strip(),
        timeout_s=int(fm.get("timeout_s", 600)),
        tools=tools,
        qa=dict(fm.get("qa") or {}),
        cwd=cwd,
        requires_approval=requires_approval,
        spec_path=path,
        spec_hash=spec_hash,
    )


def list_specs(root: Path) -> list[AgentSpec]:
    """Scan `root` recursively for *.md files; parse each as a spec.

    - Skips files starting with `.` or `_`.
    - Silently skips broken specs in Phase 1 (Phase 2+ surfaces them in UI).
    - Sorted by (domain, name) for stable listings.
    """
    if not root.is_dir():
        return []
    specs: list[AgentSpec] = []
    for p in sorted(root.rglob("*.md")):
        if p.name.startswith((".", "_")):
            continue
        try:
            specs.append(load_spec(p, root=root))
        except Exception:
            continue
    specs.sort(key=lambda s: (s.domain, s.name))
    return specs


def find_spec(root: Path, name: str) -> AgentSpec | None:
    """Find a spec by name (filename stem). Returns None if not found.

    Matches the first spec whose name == `name`. If you have ambiguous names
    across domains, prefer organizing under unique stems.
    """
    for spec in list_specs(root):
        if spec.name == name:
            return spec
    return None


# ---------- service specs (Phase 7) ----------


def load_service_spec(path: Path, *, root: Path) -> ServiceSpec:
    """Parse a single `kind: service` spec file. Required frontmatter fields
    are `kind: service` (discriminator) and `unit:` (full systemd unit name
    with suffix). `scope` defaults to 'user'. The markdown body becomes
    `description`."""
    path = path.resolve()
    root = root.resolve()
    raw = path.read_bytes()
    spec_hash = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    fm, body = parse_frontmatter(text)

    if fm.get("kind") != "service":
        raise ValueError(f"{path}: not a service spec (missing kind=service)")
    unit = fm.get("unit")
    if not unit:
        raise ValueError(f"{path}: missing required field 'unit'")
    scope = fm.get("scope", "user")
    if scope not in _VALID_SCOPES:
        raise ValueError(
            f"{path}: scope must be one of {_VALID_SCOPES}, got {scope!r}"
        )

    rel_parent = path.relative_to(root).parent
    domain = "" if rel_parent == Path(".") else str(rel_parent)

    return ServiceSpec(
        name=path.stem,
        domain=domain,
        unit=str(unit),
        scope=scope,
        purpose=str(fm.get("purpose", "")),
        description=body.strip(),
        spec_path=path,
        spec_hash=spec_hash,
    )


def list_service_specs(root: Path) -> list[ServiceSpec]:
    """Scan `root` for service specs (`kind: service`). Mirrors `list_specs`'s
    silent-skip behavior for malformed files."""
    if not root.is_dir():
        return []
    specs: list[ServiceSpec] = []
    for p in sorted(root.rglob("*.md")):
        if p.name.startswith((".", "_")):
            continue
        try:
            specs.append(load_service_spec(p, root=root))
        except Exception:
            continue
    specs.sort(key=lambda s: (s.domain, s.name))
    return specs


def find_service_spec(root: Path, name: str) -> ServiceSpec | None:
    for spec in list_service_specs(root):
        if spec.name == name:
            return spec
    return None


# ---------- workflow specs (Phase 8) ----------


def load_workflow_spec(path: Path, *, root: Path) -> WorkflowSpec:
    """Parse a `kind: workflow` spec file. Required frontmatter fields are
    `kind: workflow` and `steps:` (non-empty list of `{id, agent, prompt}`).
    The markdown body becomes `description`."""
    path = path.resolve()
    root = root.resolve()
    raw = path.read_bytes()
    spec_hash = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    fm, body = parse_frontmatter(text)

    if fm.get("kind") != "workflow":
        raise ValueError(f"{path}: not a workflow spec (missing kind=workflow)")
    raw_steps = fm.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError(f"{path}: 'steps' must be a non-empty list")

    steps: list[WorkflowStep] = []
    for i, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise ValueError(f"{path}: step {i} must be a mapping")
        agent = raw_step.get("agent")
        prompt = raw_step.get("prompt")
        if not agent:
            raise ValueError(f"{path}: step {i} missing 'agent'")
        if not prompt:
            raise ValueError(f"{path}: step {i} missing 'prompt'")
        # `id` defaults to the agent name when not given — fine for single-
        # agent-per-step workflows; users can override for clarity.
        step_id = str(raw_step.get("id") or agent)
        steps.append(WorkflowStep(id=step_id, agent=str(agent), prompt=str(prompt)))

    rel_parent = path.relative_to(root).parent
    domain = "" if rel_parent == Path(".") else str(rel_parent)

    return WorkflowSpec(
        name=path.stem,
        domain=domain,
        description=body.strip(),
        steps=steps,
        spec_path=path,
        spec_hash=spec_hash,
    )


def list_workflow_specs(root: Path) -> list[WorkflowSpec]:
    """Scan `root` for `kind: workflow` specs. Mirrors `list_specs`'s
    silent-skip on parse error."""
    if not root.is_dir():
        return []
    specs: list[WorkflowSpec] = []
    for p in sorted(root.rglob("*.md")):
        if p.name.startswith((".", "_")):
            continue
        try:
            specs.append(load_workflow_spec(p, root=root))
        except Exception:
            continue
    specs.sort(key=lambda s: (s.domain, s.name))
    return specs


def find_workflow_spec(root: Path, name: str) -> WorkflowSpec | None:
    for spec in list_workflow_specs(root):
        if spec.name == name:
            return spec
    return None


# ---------- trigger specs (Phase 9) ----------


_VALID_TARGET_KINDS = ("agent", "workflow")


def load_trigger_spec(path: Path, *, root: Path) -> TriggerSpec:
    """Parse a `kind: trigger` spec file. Required frontmatter:
      schedule, target_kind ('agent' or 'workflow'), target, prompt.
    Validates the cron expression eagerly so an invalid trigger never
    reaches the scheduler."""
    path = path.resolve()
    root = root.resolve()
    raw = path.read_bytes()
    spec_hash = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    fm, body = parse_frontmatter(text)

    if fm.get("kind") != "trigger":
        raise ValueError(f"{path}: not a trigger spec (missing kind=trigger)")
    schedule = fm.get("schedule")
    target_kind = fm.get("target_kind")
    target = fm.get("target")
    prompt = fm.get("prompt")
    if not schedule:
        raise ValueError(f"{path}: missing required field 'schedule'")
    if target_kind not in _VALID_TARGET_KINDS:
        raise ValueError(
            f"{path}: target_kind must be one of {_VALID_TARGET_KINDS}, "
            f"got {target_kind!r}"
        )
    if not target:
        raise ValueError(f"{path}: missing required field 'target'")
    if not prompt:
        raise ValueError(f"{path}: missing required field 'prompt'")

    # Parse the cron at load time so an invalid expression is a load
    # error, not a tick-time error inside the scheduler.
    from ..runtime.cron import parse_cron
    parse_cron(str(schedule))

    rel_parent = path.relative_to(root).parent
    domain = "" if rel_parent == Path(".") else str(rel_parent)

    return TriggerSpec(
        name=path.stem,
        domain=domain,
        schedule=str(schedule),
        target_kind=str(target_kind),
        target=str(target),
        prompt=str(prompt),
        description=body.strip(),
        spec_path=path,
        spec_hash=spec_hash,
    )


def list_trigger_specs(root: Path) -> list[TriggerSpec]:
    if not root.is_dir():
        return []
    specs: list[TriggerSpec] = []
    for p in sorted(root.rglob("*.md")):
        if p.name.startswith((".", "_")):
            continue
        try:
            specs.append(load_trigger_spec(p, root=root))
        except Exception:
            continue
    specs.sort(key=lambda s: (s.domain, s.name))
    return specs


def find_trigger_spec(root: Path, name: str) -> TriggerSpec | None:
    for spec in list_trigger_specs(root):
        if spec.name == name:
            return spec
    return None
