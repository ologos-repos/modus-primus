# Network Topology — Agents Console Reference

This kit takes no opinion on private connectivity. Same posture as the sibling chat console kit (see `../chat-console-reference/network/README.md`); the agents console binds to a port (`8091` by default) and trusts the network layer underneath for access control, encryption, and host reachability. Adopters supply the private-connectivity substrate.

## Agents-specific connectivity concerns

The agents console has tighter outbound reachability requirements than the chat console because it actively spawns agent invocations against cognitive substrates:

- **Cognitive substrate adapters reach inference endpoints.** For Scenario 2 (self-hosted open-weights), the agents console reaches the in-house inference platform (`[ENTERPRISE: inference platform endpoint — typically vLLM, TGI, Triton, RayServe-class behind an enterprise gateway]`). For Scenario 1 (commercial cloud-hosted), it reaches vendor API endpoints (`[ENTERPRISE: vendor API endpoint]`).
- **Audit federation bus emission.** Per the parent baseline `execution-runtime.md` (B.8.2.10), every run emits structured audit records; the network must route those to `[ENTERPRISE: audit aggregation / SIEM]`.
- **Sibling-service back-links.** The agents console proxies invocations into / from the chat console for human-in-the-loop scenarios; the chat-console URL must be reachable.
- **Notifier webhook delivery (if configured).** Run-completion notifications route to `[ENTERPRISE: notifier webhook endpoint]`; outbound HTTPS must be permitted to that destination.

## Reference patterns

See `../chat-console-reference/network/README.md` for the VPN / overlay / zero-trust adapter pattern catalog. The same options apply to the agents console.

## Smoke verification

After deploying, verify:

1. **Agents console reachability** — humans or sibling consoles can reach the agents URL.
2. **Inference reachability** — substrate adapter health-check passes (the kit's `src/runtime/ollama_backend.py` and `src/runtime/openai_backend.py` smoke-check on startup).
3. **Audit emission reaches the bus** — run a hello-world spec (`src/specs/research/hello-world.md`) and verify the run lands in `[ENTERPRISE: audit federation bus]`.

If any fails, network configuration is the first place to inspect.
