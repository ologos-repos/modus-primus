"""Tests for runtime/ollama_hosts.load_hosts."""
from __future__ import annotations

import json
from pathlib import Path

from means.agents.runtime.ollama_hosts import load_hosts, _DEFAULT_HOSTS_PATH


def test_default_file_loads_known_aliases():
    """The shipped default file in means/agents/data/ollama_hosts.json
    contains the peakai + tracys-mac aliases."""
    hosts = load_hosts()
    assert "peakai" in hosts
    assert "tracys-mac" in hosts
    assert hosts["peakai"].startswith("http://")


def test_missing_file_returns_empty(tmp_path: Path):
    """A missing config file is treated as 'no aliases configured'; the
    real failure surface is the alias-not-found error in OllamaBackend."""
    p = tmp_path / "nonexistent.json"
    assert load_hosts(p) == {}


def test_override_path(tmp_path: Path):
    p = tmp_path / "hosts.json"
    p.write_text(json.dumps({"local": "http://127.0.0.1:11434"}))
    assert load_hosts(p) == {"local": "http://127.0.0.1:11434"}


def test_default_path_points_at_data_dir():
    """Sanity: the default points inside means/agents/data/."""
    assert _DEFAULT_HOSTS_PATH.name == "ollama_hosts.json"
    assert _DEFAULT_HOSTS_PATH.parent.name == "data"
