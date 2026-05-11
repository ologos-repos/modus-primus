# Network Topology — Chat Console Reference

This kit takes no opinion on private connectivity. The chat console binds to a port (`8080` by default) and trusts the network layer underneath for access control, encryption, and host reachability. Adopters supply the private-connectivity substrate.

## What the kit assumes

- The chat console runs on a host inside the enterprise's private network (or accessible via private overlay).
- Outbound network access from the console reaches:
  - The cognitive substrate (inference platform or vendor API endpoint)
  - The agents console (if deployed alongside)
  - Observability / audit ingest endpoints
  - Optional integrations (email, paging, ticketing)
- Inbound access to the console comes from:
  - Authorized humans (engineers, SREs, security analysts) operating within their domain authority
  - Authorized sibling agents (the agents console may proxy invocations into the chat console for human-in-the-loop scenarios)

## What the kit does *not* prescribe

The reference does not pick a VPN technology, network topology, or perimeter model. Representative adopter options (illustrative, not normative):

### Mesh VPN / overlay network

| Class | Representative platforms |
|---|---|
| Mesh / SD-WAN overlay | `[ENTERPRISE: mesh VPN — Tailscale, ZeroTier, Netmaker, Twingate, or equivalent]` |
| Site-to-site VPN | `[ENTERPRISE: VPN concentrator — Cisco AnyConnect, Fortinet, Palo Alto, OpenVPN-class, WireGuard concentrator]` |
| Cloud-private endpoints | `[ENTERPRISE: cloud-private connectivity — AWS PrivateLink, Azure Private Endpoints, GCP Private Service Connect]` |
| Zero-trust gateway | `[ENTERPRISE: ZT proxy — Cloudflare Access, BeyondCorp-class, ZTNA platform]` |

The reference assumes the chosen platform provides:
- Host-to-host reachability between console deployments and sibling services
- Identity-aware access for human operators
- Audit logs ingested into the enterprise SIEM (CyberOps governance)

### Host addressing

The kit references hosts by role (`[ENTERPRISE: workstation hostname]`, `[ENTERPRISE: inference host address]`, etc.) rather than by IP, hostname, or DNS name. Real deployments resolve these to:

- DNS names on the enterprise's internal DNS
- Overlay-network MagicDNS-class hostnames
- IP addresses in the private-network range
- Cloud-native service identifiers (Kubernetes service names, AWS endpoints, etc.)

The reference does not pick.

### Cross-domain reachability

When the chat console is deployed in one enclave (e.g., unclassified GovCloud-equivalent) and sibling services or human operators access from another enclave, cross-enclave reachability is the enterprise's network architecture concern. The Modus Primus spec scopes federation to the *governance and audit* layer (§4.7); the *network* layer is the adopter's:

- Cross-domain solutions (CDS) for classified ↔ unclassified bridging
- Bastion / jump-host patterns
- Cross-VPC / cross-cloud peering
- Federated identity for cross-enclave user access

Note: per Modus Primus §4.7, cross-enclave *governance artifacts* (federation schema, audit aggregation, capability registry templates) cross the boundary; operational data does not. The network architecture should preserve this asymmetry.

## Smoke verification

After deploying, verify:

1. **Console reachability from the operator side** — humans can reach the console URL through the chosen access path.
2. **Console outbound reachability** — the console can reach the cognitive substrate, sibling services, and observability endpoints. The console's startup logs surface connectivity failures.
3. **Audit emission** — actions taken in the console produce records in `[ENTERPRISE: audit federation bus]`. Verify schema conformance against the enclave audit federation schema.

If any of the three fails, the network configuration is the first place to inspect, not the console.
