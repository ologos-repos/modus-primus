"""Agents service — standalone aiohttp app for the agent fleet console.

Decoupled from the chat console ([ENTERPRISE: tracker ref]). Runs on its own port (default
8081) with its own systemd unit. Cross-link to chat is configured via
CHAT_CONSOLE_URL env var; agent run completions are pushed to chat over
HTTP rather than injected in-process.

Run: `python -m means.agents.app` from AGENTS_CONSOLE_WORKSPACE, or use the service
template at means/agents/agents.service.template.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from aiohttp import web

from . import routes as agent_routes


logger = logging.getLogger(__name__)

_PKG_ROOT = Path(__file__).resolve().parent


def build_app() -> web.Application:
    app = web.Application()
    agent_routes.register_routes(app)

    static_dir = _PKG_ROOT / "web" / "static"
    if static_dir.is_dir():
        app.router.add_static("/static/", path=str(static_dir), name="static")

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    host = os.environ.get("AGENTS_HOST", "0.0.0.0")
    port = int(os.environ.get("AGENTS_PORT", "8081"))
    web.run_app(build_app(), host=host, port=port)


if __name__ == "__main__":
    main()
