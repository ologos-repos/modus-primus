"""Named-host registry for the Ollama backend.

Ollama specs declare hosts by alias — `model: ollama:peakai/qwen3:14b` —
rather than embedding raw IPs/ports, so a host moving doesn't ripple into
every spec. Aliases live in `means/agents/data/ollama_hosts.json`; ops can
add a host by editing that file (no code change). The daemon re-reads on
each `select_backend` call (one read per launch — negligible) so changes
take effect without restart.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


_DEFAULT_HOSTS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "ollama_hosts.json"
)


def load_hosts(path: Optional[Path] = None) -> dict[str, str]:
    """Return {alias: base_url}. Missing file → empty dict (the alias-not-
    found error in OllamaBackend's constructor is the user-facing surface;
    a missing config is the same failure mode as an unknown alias)."""
    p = path or _DEFAULT_HOSTS_PATH
    if not p.exists():
        return {}
    return json.loads(p.read_text())
