# Roadmap

Each phase ends in something that works and is merged. Later phases are
intentionally less detailed.

| # | Phase | Outcome | Status |
|---|---|---|---|
| 0 | Pipeline | CI/CD, scanning, releases to ghcr.io | Done |
| 1 | Design | Architecture doc, decision records, Claude configuration | In progress |
| 2 | Garmin spike | Login and MFA confirmed, list of available metrics, scrubbed fixtures; ADR 9 accepted or revised | Next |
| 3 | Storage and collector | Schema and migrations, raw and normalised layers, `collect` for one user from the command line | |
| 4 | Web foundation | `serve`, accounts, invites, Garmin link flow, base layout and styling | |
| 5 | Dashboards | Overview plus pages per metric family, date range selection | |
| 6 | Publish | Tunnel hostname, Cloudflare Access, installable on Android, self-hosting guide | |
| 7 | Goals | Goal management per user | |
| 8 | AI analysis | Claude-based analysis and training recommendations | |

## Phase 2 in detail

A throwaway script, run locally against a real account, never in CI:

1. Log in with `python-garminconnect`, including MFA, and persist tokens to
   `.garmin-tokens/` (git-ignored).
2. Restart and confirm the stored tokens work without logging in again.
3. Call every data endpoint the library offers for one recent day and one
   activity; save the responses.
4. Produce a table of metric families: endpoint, granularity, history depth.
5. Scrub the responses and commit them as fixtures under `tests/fixtures/`.

Exit criteria: we know the login flow we have to build in the web UI, how long
tokens last, and which metrics exist.
