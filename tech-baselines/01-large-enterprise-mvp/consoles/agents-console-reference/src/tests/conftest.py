"""Pytest config — adds the repo root to sys.path so tests can import
`means.agents.<x>` and modules can use relative imports cleanly across
subpackages (e.g. `from ..specs.model import AgentSpec` inside runtime/).
The daemon, when invoked as `python -m means.agents.runtime.daemon`,
uses the same import resolution shape, so test + production paths agree.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
