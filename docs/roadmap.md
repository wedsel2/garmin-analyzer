# Roadmap

Each phase ends in something that works and is merged. Later phases are
intentionally less detailed.

| # | Phase | Outcome | Status |
|---|---|---|---|
| 0 | Pipeline | CI/CD, scanning, releases to ghcr.io | Done |
| 1 | Design | Architecture doc, decision records, Claude configuration | Done |
| 2 | Garmin spike | Browser-assisted login confirmed, 70 endpoints probed, [findings](garmin-spike.md) written, ADR 9 revised | Done (token refresh still to confirm) |
| 3 | Storage and collector | Schema and migrations, raw and normalised layers, `collect` for one user from the command line; scrubbed fixtures per metric family | In progress: schema, migrations, fixture scrubbing and the normalised tables for wellness and training metrics done; activities still raw-only; token encryption and collector next |
| 4 | Web foundation | `serve`, accounts, invites, Garmin link flow, base layout and styling | |
| 5 | Dashboards | Overview plus pages per metric family, date range selection | |
| 6 | Publish | Tunnel hostname, Cloudflare Access, installable on Android, self-hosting guide | |
| 7 | Goals | Goal management per user | |
| 8 | AI analysis | Claude-based analysis and training recommendations | |

## Phase 2 outcome

See the [spike findings](garmin-spike.md). One check remains: run
`uv run scripts/garmin_spike.py` again after the access token has expired (about
26 hours after linking) and confirm it logs in from stored tokens without a new
browser sign-in.
