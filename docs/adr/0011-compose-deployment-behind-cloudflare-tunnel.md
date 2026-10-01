# 11. Deploy with Docker Compose, publish through a Cloudflare tunnel

- Status: Accepted
- Date: 2026-10-01

## Context

The owner runs Proxmox with a Home Assistant OS VM and an Ubuntu VM, and already
publishes Home Assistant through a Cloudflare tunnel. The app must be reachable
by friends from the internet and be easy for others to self-host.

## Decision

- The supported deployment is **Docker Compose on a Linux host**: services `web`
  and `worker` from the same image, plus PostgreSQL, configured by a `.env` file.
- The reference instance runs in the **Ubuntu VM**, not directly on Proxmox.
- The instance is published as **its own hostname on the existing Cloudflare
  tunnel**, pointing at the `web` service, with **Cloudflare Access** in front.
- Home Assistant is not in the request path. It may show the app as a sidebar
  webpage panel.

## Alternatives considered

- **Container directly on Proxmox (LXC)**: saves some overhead, but the compose
  stack would need translating, and it puts application workloads on the
  hypervisor.
- **Home Assistant add-on with ingress**: only on Home Assistant OS, ties login
  to Home Assistant users, and is a second packaging format to maintain.
- **Opening a port with a reverse proxy**: exposes the home network; the tunnel
  already exists.

## Consequences

- Self-hosters need only Docker and the compose file; the tunnel and Access are
  optional and documented separately.
- The app must work correctly behind a proxy (forwarded headers, secure cookies).
- Friends pass Cloudflare Access and then log in to the app: two steps, accepted
  for the extra protection of health data.
- Backups are the PostgreSQL volume plus the `.env` file (which holds the token
  encryption key).
