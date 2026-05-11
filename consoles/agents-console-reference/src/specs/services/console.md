---
kind: service
unit: console.service
purpose: chat console — web control surface (port 8080)
---
The aiohttp server hosting the chat surface, fleet panel, and agent runtime
routes. Auto-starts at login. Tailscale-accessible at `[ENTERPRISE: workstation host address]:8080`.

See [missions/projects/console.md](../../../../missions/projects/console.md).
