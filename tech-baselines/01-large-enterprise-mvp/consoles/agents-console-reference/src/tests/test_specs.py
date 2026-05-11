"""Tests for specs/. Frontmatter parsing, AgentSpec loading, list_specs scan,
spec_hash stability + sensitivity, missing-field + invalid-fork validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from means.agents.specs.loader import find_spec, list_specs, load_spec, parse_frontmatter


# ---------- frontmatter parser ----------


def test_parse_frontmatter_happy_path():
    text = "---\nmodel: claude-sonnet-4-7\nfork: dev\n---\nbody text\n"
    fm, body = parse_frontmatter(text)
    assert fm == {"model": "claude-sonnet-4-7", "fork": "dev"}
    assert body == "body text\n"


def test_parse_frontmatter_no_delimiters():
    text = "no frontmatter here\n"
    fm, body = parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_parse_frontmatter_unclosed_delimiters():
    text = "---\nmodel: foo\nbody"
    fm, body = parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_parse_frontmatter_empty_block():
    text = "---\n---\nbody\n"
    fm, body = parse_frontmatter(text)
    assert fm == {}
    assert body == "body\n"


def test_parse_frontmatter_non_mapping_raises():
    with pytest.raises(ValueError, match="mapping"):
        parse_frontmatter("---\n- item1\n- item2\n---\n")


# ---------- load_spec ----------


def test_load_spec_minimal(tmp_path: Path):
    root = tmp_path / "specs"
    research = root / "research"
    research.mkdir(parents=True)
    p = research / "hello.md"
    p.write_text("---\nmodel: claude-sonnet-4-7\n---\nSystem prompt.\n")

    spec = load_spec(p, root=root)
    assert spec.name == "hello"
    assert spec.domain == "research"
    assert spec.fork == "dev"
    assert spec.model == "claude-sonnet-4-7"
    assert spec.system_prompt == "System prompt."
    assert spec.timeout_s == 600
    # Phase 2: tools missing → None (resolves to fork defaults at runtime)
    assert spec.tools is None
    assert spec.qa == {}
    assert spec.cwd is None
    assert len(spec.spec_hash) == 64


def test_load_spec_full_frontmatter(tmp_path: Path):
    p = tmp_path / "ops.md"
    p.write_text(
        "---\nfork: infraops\nmodel: claude-opus-4-7\n"
        "timeout_s: 30\ntools: [shell.run, fs.read]\n"
        "qa: {tests_pass: true, diff_minimal: true}\n---\nDo ops things.\n"
    )
    spec = load_spec(p, root=tmp_path)
    assert spec.fork == "infraops"
    assert spec.model == "claude-opus-4-7"
    assert spec.timeout_s == 30
    assert spec.tools == ["shell.run", "fs.read"]
    assert spec.qa == {"tests_pass": True, "diff_minimal": True}


def test_load_spec_root_domain_is_empty(tmp_path: Path):
    """A spec at the specs root (no subdirectory) has empty domain."""
    p = tmp_path / "loose.md"
    p.write_text("---\nmodel: m\n---\nbody\n")
    spec = load_spec(p, root=tmp_path)
    assert spec.domain == ""


def test_load_spec_missing_model_raises(tmp_path: Path):
    p = tmp_path / "bad.md"
    p.write_text("---\nfork: dev\n---\nbody\n")
    with pytest.raises(ValueError, match="model"):
        load_spec(p, root=tmp_path)


def test_load_spec_invalid_fork_raises(tmp_path: Path):
    p = tmp_path / "bad.md"
    p.write_text("---\nmodel: foo\nfork: madeup\n---\nbody\n")
    with pytest.raises(ValueError, match="fork"):
        load_spec(p, root=tmp_path)


def test_load_spec_strips_body_whitespace(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: m\n---\n\n  System prompt.  \n\n")
    spec = load_spec(p, root=tmp_path)
    assert spec.system_prompt == "System prompt."


def test_load_spec_to_summary(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: m\nfork: dev\n---\nbody")
    summary = load_spec(p, root=tmp_path).to_summary()
    assert summary["name"] == "x"
    assert summary["model"] == "m"
    assert summary["fork"] == "dev"
    assert "spec_hash" in summary
    assert "cwd" in summary
    assert "spec_path" not in summary  # path is internal
    # Phase 2: summary projects effective tools (post fork-defaults resolution),
    # so a dev-fork spec with tools missing shows the dev defaults.
    assert summary["tools"] == ["Read", "Edit", "Bash", "Grep"]


# ---------- tools + cwd (Phase 2) ----------


def test_load_spec_tools_missing_is_none(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: m\n---\nbody")
    spec = load_spec(p, root=tmp_path)
    assert spec.tools is None  # missing → None → fork defaults at runtime


def test_load_spec_tools_explicit_empty(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: m\ntools: []\n---\nbody")
    spec = load_spec(p, root=tmp_path)
    assert spec.tools == []  # explicit [] → no tools (single-shot)


def test_load_spec_tools_populated(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: m\ntools: [Read, Edit, Bash]\n---\nbody")
    spec = load_spec(p, root=tmp_path)
    assert spec.tools == ["Read", "Edit", "Bash"]


def test_load_spec_tools_with_restriction_syntax(tmp_path: Path):
    """Tool names like 'Bash(git *)' (parenthesized restrictions) pass through verbatim."""
    p = tmp_path / "x.md"
    p.write_text('---\nmodel: m\ntools: ["Bash(git *)", Edit]\n---\nbody')
    spec = load_spec(p, root=tmp_path)
    assert spec.tools == ["Bash(git *)", "Edit"]


def test_load_spec_cwd_missing_is_none(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: m\n---\nbody")
    spec = load_spec(p, root=tmp_path)
    assert spec.cwd is None


def test_load_spec_cwd_set(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: m\ncwd: /opt/agent-work\n---\nbody")
    spec = load_spec(p, root=tmp_path)
    assert spec.cwd == "/opt/agent-work"


# ---------- requires_approval (Phase 4) ----------


def test_load_spec_requires_approval_default_false(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: m\n---\nbody")
    spec = load_spec(p, root=tmp_path)
    assert spec.requires_approval is False


def test_load_spec_requires_approval_true(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: m\nrequires_approval: true\n---\nbody")
    spec = load_spec(p, root=tmp_path)
    assert spec.requires_approval is True


def test_load_spec_requires_approval_false_explicit(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: m\nrequires_approval: false\n---\nbody")
    spec = load_spec(p, root=tmp_path)
    assert spec.requires_approval is False


# ---------- provider / model_id (Phase 6) ----------


def test_provider_default_claude_for_bare_model(tmp_path: Path):
    """`model: sonnet` (no colon) → provider defaults to 'claude'."""
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: sonnet\n---\nbody")
    spec = load_spec(p, root=tmp_path)
    assert spec.provider == "claude"
    assert spec.model_id == "sonnet"


def test_provider_explicit_claude(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: claude:opus\n---\nbody")
    spec = load_spec(p, root=tmp_path)
    assert spec.provider == "claude"
    assert spec.model_id == "opus"


def test_provider_openai(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: openai:gpt-4o-mini\n---\nbody")
    spec = load_spec(p, root=tmp_path)
    assert spec.provider == "openai"
    assert spec.model_id == "gpt-4o-mini"


def test_provider_ollama_with_slash_and_colon(tmp_path: Path):
    """`ollama:peakai/qwen3:14b` — only the FIRST colon splits provider from
    model_id, so the model tag's `:14b` survives intact."""
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: ollama:peakai/qwen3:14b\n---\nbody")
    spec = load_spec(p, root=tmp_path)
    assert spec.provider == "ollama"
    assert spec.model_id == "peakai/qwen3:14b"


def test_provider_case_insensitive(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: OpenAI:gpt-4o\n---\nbody")
    spec = load_spec(p, root=tmp_path)
    assert spec.provider == "openai"
    assert spec.model_id == "gpt-4o"


def test_provider_in_summary(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: gemini:gemini-2.5-flash\n---\nbody")
    summary = load_spec(p, root=tmp_path).to_summary()
    assert summary["provider"] == "gemini"


# ---------- spec_hash stability ----------


def test_spec_hash_stable_across_loads(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: m\n---\nbody\n")
    h1 = load_spec(p, root=tmp_path).spec_hash
    h2 = load_spec(p, root=tmp_path).spec_hash
    assert h1 == h2


def test_spec_hash_differs_on_content_change(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: m\n---\nv1\n")
    h1 = load_spec(p, root=tmp_path).spec_hash
    p.write_text("---\nmodel: m\n---\nv2\n")
    h2 = load_spec(p, root=tmp_path).spec_hash
    assert h1 != h2


def test_spec_hash_differs_on_whitespace_change(tmp_path: Path):
    """Hash is sensitive to any byte change so audit catches even prompt-edit drift."""
    p = tmp_path / "x.md"
    p.write_text("---\nmodel: m\n---\nbody\n")
    h1 = load_spec(p, root=tmp_path).spec_hash
    p.write_text("---\nmodel: m\n---\nbody\n\n")  # extra newline
    h2 = load_spec(p, root=tmp_path).spec_hash
    assert h1 != h2


# ---------- list_specs ----------


def test_list_specs_recursive(tmp_path: Path):
    (tmp_path / "dev").mkdir()
    (tmp_path / "dev" / "a.md").write_text("---\nmodel: m\n---\nbody")
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "b.md").write_text("---\nmodel: m\nfork: infraops\n---\nbody")
    (tmp_path / "loose.md").write_text("---\nmodel: m\n---\nbody")

    specs = list_specs(tmp_path)
    names = [s.name for s in specs]
    assert sorted(names) == ["a", "b", "loose"]


def test_list_specs_sorted_by_domain_then_name(tmp_path: Path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    (tmp_path / "alpha" / "z.md").write_text("---\nmodel: m\n---\n")
    (tmp_path / "beta" / "a.md").write_text("---\nmodel: m\n---\n")
    (tmp_path / "alpha" / "a.md").write_text("---\nmodel: m\n---\n")

    specs = list_specs(tmp_path)
    assert [(s.domain, s.name) for s in specs] == [
        ("alpha", "a"),
        ("alpha", "z"),
        ("beta", "a"),
    ]


def test_list_specs_skips_dot_and_underscore(tmp_path: Path):
    (tmp_path / "ok.md").write_text("---\nmodel: m\n---\nbody")
    (tmp_path / "_skip.md").write_text("---\nmodel: m\n---\nbody")
    (tmp_path / ".hidden.md").write_text("---\nmodel: m\n---\nbody")

    specs = list_specs(tmp_path)
    assert [s.name for s in specs] == ["ok"]


def test_list_specs_skips_broken(tmp_path: Path):
    (tmp_path / "good.md").write_text("---\nmodel: m\n---\nbody")
    (tmp_path / "no-model.md").write_text("---\nfork: dev\n---\n")

    specs = list_specs(tmp_path)
    assert [s.name for s in specs] == ["good"]


def test_list_specs_empty_dir(tmp_path: Path):
    assert list_specs(tmp_path) == []


def test_list_specs_nonexistent_dir(tmp_path: Path):
    assert list_specs(tmp_path / "does-not-exist") == []


# ---------- find_spec ----------


def test_find_spec_hits(tmp_path: Path):
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "hello.md").write_text("---\nmodel: m\n---\nhi\n")
    spec = find_spec(tmp_path, "hello")
    assert spec is not None
    assert spec.name == "hello"


def test_find_spec_misses(tmp_path: Path):
    assert find_spec(tmp_path, "ghost") is None


# ---------- the canonical hello-world spec ----------


def test_canonical_file_reader_loads():
    """Smoke test the actual `means/agents/specs/research/file-reader.md`."""
    pkg_root = Path(__file__).parent.parent
    specs_root = pkg_root / "specs"
    spec = find_spec(specs_root, "file-reader")
    assert spec is not None
    assert spec.fork == "dev"
    assert spec.tools == ["Read", "Bash"]
    assert "file-reading helper" in spec.system_prompt


def test_canonical_hello_world_loads():
    """Smoke test the actual `means/agents/specs/research/hello-world.md`."""
    pkg_root = Path(__file__).parent.parent
    specs_root = pkg_root / "specs"
    spec = find_spec(specs_root, "hello-world")
    assert spec is not None
    assert spec.fork == "dev"
    # 'sonnet' alias resolves to Sonnet 4.6 inside claude CLI; full IDs work too
    assert spec.model in ("sonnet", "opus", "haiku") or spec.model.startswith("claude-")
    assert "research helper" in spec.system_prompt
    # Phase 2: hello-world is preserved as single-shot via explicit `tools: []`.
    assert spec.tools == []


def test_canonical_ollama_hello_loads():
    """Phase 6 smoke: ollama-hello.md parses with provider='ollama'."""
    pkg_root = Path(__file__).parent.parent
    spec = find_spec(pkg_root / "specs", "ollama-hello")
    assert spec is not None
    assert spec.provider == "ollama"
    assert spec.model_id.startswith("tracys-mac/")
    assert spec.tools == []


def test_canonical_openai_hello_loads():
    pkg_root = Path(__file__).parent.parent
    spec = find_spec(pkg_root / "specs", "openai-hello")
    assert spec is not None
    assert spec.provider == "openai"
    assert spec.model_id == "gpt-4o-mini"


def test_canonical_gemini_hello_loads():
    pkg_root = Path(__file__).parent.parent
    spec = find_spec(pkg_root / "specs", "gemini-hello")
    assert spec is not None
    assert spec.provider == "gemini"
    assert spec.model_id.startswith("gemini-")
