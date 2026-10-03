# Roadmap

Each phase ends in something that works and is merged. Later phases are
intentionally less detailed.

| # | Phase | Outcome | Status |
|---|---|---|---|
| 0 | Pipeline | CI/CD, scanning, releases to ghcr.io | Done |
| 1 | Design | Architecture doc, decision records, Claude configuration | Done |
| 2 | Garmin spike | Browser-assisted login confirmed, 70 endpoints probed, [findings](garmin-spike.md) written, ADR 9 revised | Done |
| 3 | Storage and collector | Schema and migrations, raw and normalised layers, synthetic fixtures per metric family, token encryption, and `user-add`, `link` and `collect` from the command line | Done, first live run on 2026-10-03 |
| 4 | Web foundation | `serve`, accounts, invites, Garmin link flow, base layout and styling, and a scheduled worker that runs `collect` | Next |
| 5 | Dashboards | Overview plus pages per metric family, date range selection | |
| 6 | Publish | Tunnel hostname, Cloudflare Access, installable on Android, self-hosting guide | |
| 7 | Goals | Goal management per user | |
| 8 | AI analysis | Claude-based analysis and training recommendations | |

## Phase 2 and 3 outcome

See the [spike findings](garmin-spike.md), which include the token refresh check
and the first live collection.

## Deferred on purpose

- **Per-second activity samples as a table** (heart rate, pace, cadence, power,
  position). Everything needed to build it is stored; see
  [ADR 12](adr/0012-activities-stored-in-full.md). Pick this up when a feature
  needs analysis across activities, such as a power curve or time at pace.
- **Parsers for pulse ox, endurance score, hill score and lactate threshold
  heart rate and speed.** They need a sample from an account that has the data.
- **Activity weather and exercise sets** as tables. Stored raw only.
