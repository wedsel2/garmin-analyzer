# Roadmap

Each phase ends in something that works and is merged. Later phases are
intentionally less detailed.

| # | Phase | Outcome | Status |
|---|---|---|---|
| 0 | Pipeline | CI/CD, scanning, releases to ghcr.io | Done |
| 1 | Design | Architecture doc, decision records, Claude configuration | Done |
| 2 | Garmin spike | Browser-assisted login confirmed, 70 endpoints probed, [findings](garmin-spike.md) written, ADR 9 revised | Done |
| 3 | Storage and collector | Schema and migrations, raw and normalised layers, synthetic fixtures per metric family, token encryption, and `user-add`, `link` and `collect` from the command line | Done, first live run on 2026-10-03 |
| 4 | Web foundation | `serve`, accounts, invites, Garmin link flow, base layout and styling, and a scheduled worker that runs `collect` | Done |
| 5 | Dashboards | Overview plus pages per metric family, date range selection | Done |
| 6 | Publish | Tunnel hostname, Cloudflare Access, installable on Android, [self-hosting guide](self-hosting.md) | Done, published on 2026-10-04 |
| 7 | Goals | Events to train for and weekly goals per user, on their own page and on the overview | Done |
| 8 | AI analysis | Claude-based analysis and training recommendations | |

## Phase 2 and 3 outcome

See the [spike findings](garmin-spike.md), which include the token refresh check
and the first live collection.

## Phase 5 order

1. Series API, chart script and the overview. Done.
2. Recovery and sleep pages, with a period to pick. Done.
3. Day view: intraday heart rate, stress, body battery, steps, respiration and
   HRV on one time axis, bucketed on the server. Done.
4. Training page. Done.
5. Activities list and detail, with the route drawn as a line without a map. Done.

## Phase 6 order

1. Manifest, icons and a service worker with an offline page. Done.
2. Behind a proxy: tests, and a line in the log for a proxy that is not
   trusted. Done.
3. Self-hosting guide. Done.
4. The owner's instance: hostname on the tunnel, Access, and installing on a
   phone. Done on 2026-10-04: the tunnel runs in the Cloudflared add-on of Home
   Assistant on another machine, whose address is the one to trust, and Chrome
   on Android installed the site through Access without a bypass.

## Deferred on purpose

- **A goal on a collected metric**, such as VO2 max or resting heart rate by a
  date. Left out of phase 7 by choice; see
  [ADR 20](adr/0020-goals-as-two-tables-progress-computed.md).
- **Goals in the JSON API.** They have pages only until a chart or another
  client needs them.

- **A street map under the route of an activity.** Map tiles come from a third
  party, which would learn where a user trains and needs an exception in the
  content security policy. Needs its own decision record.

- **Per-second activity samples as a table** (heart rate, pace, cadence, power,
  position). Everything needed to build it is stored; see
  [ADR 12](adr/0012-activities-stored-in-full.md). Pick this up when a feature
  needs analysis across activities, such as a power curve or time at pace.
- **Parsers for pulse ox, endurance score, hill score and lactate threshold
  heart rate and speed.** They need a sample from an account that has the data.
- **Activity weather and exercise sets** as tables. Stored raw only.

## Known limits of the collector

Found in a review on 2026-10-03 and left as they are, because each needs a rare
coincidence. Pick one up when it shows in real data.

- **Activity details are fetched once.** An activity synced while Garmin is
  still processing it keeps whatever was empty then; the weekly catch-up covers
  days, not activities. An activity without an original file is asked for again
  on every sync that lists it.
- **`max_metrics` is stored under the period it was asked for**, so every day
  adds a raw row instead of replacing one.
- **"Today" is the date of the server clock, in UTC.** For a user west of UTC a
  day can get its last regular refetch before it has ended, and stays
  incomplete until the weekly catch-up.
- **A 401 in the middle of a sync marks the link as needing a new sign-in**,
  also in the unlikely case that it came from a token refresh that failed on a
  network error. `collect <email>` makes the link active again when the tokens
  still work.
- **Days for which Garmin answers nothing at all** on the daily summary, heart
  rate or floors count as failed requests, not as empty, and are asked for
  again by every sync that covers them. Not yet seen in practice.
- **`link` holds the sync lock while it waits for the pasted address**, so a
  prompt left open makes syncs skip that user. Linking in the browser takes the
  lock only for the ticket exchange.
