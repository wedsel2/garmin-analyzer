# Architecture

Target design. What exists today is the pipeline, the database schema, the
collector run from the command line (`user-add`, `link` and `collect`), and the
start of the web interface: `serve`, setting up the first account, signing in,
inviting and managing users, linking Garmin, and the base layout and styling.
Dashboards and the scheduled worker are next. See the [roadmap](roadmap.md) for
the order of work and the [decision records](adr/README.md) for the reasoning.

## Goal

A self-hosted web app where a small group (the owner and friends) can each link
a Garmin account, have all available metrics collected automatically, and explore
them in a clean web interface that also installs as an app on Android. Later:
goals and AI-based training recommendations. Others should be able to self-host
their own instance with little effort.

## Components

```text
                     Internet
                        │
              Cloudflare (Access, tunnel)          optional, per instance
                        │
        ┌───────────────┼──────────────── Docker host (compose) ──┐
        │               ▼                                          │
        │   web  ── garmin-analyzer serve ──┐                      │
        │           FastAPI: pages + JSON API│                     │
        │                                    ├──►  PostgreSQL      │
        │   worker ─ garmin-analyzer collect ┘                     │
        │           scheduled sync per linked user                 │
        └───────────────│──────────────────────────────────────────┘
                        ▼
                 Garmin Connect (unofficial API)
```

| Component | Responsibility |
|---|---|
| **web** | Login, user and invite management, Garmin link flow, dashboards, JSON API |
| **worker** | Backfill on link, then incremental sync per user; rate-limited and resumable |
| **PostgreSQL** | Users, encrypted Garmin tokens, raw payloads, normalised metrics, later goals |

`web` and `worker` are the same image started with different commands, so there
is one artifact to build, scan and release.

## Web interface

Server-rendered pages (Jinja templates) with HTMX for partial updates, Tailwind
CSS with a component kit for styling, and ECharts for charts. Chart data comes
from the same JSON API a future native client would use. A web app manifest and
service worker make the site installable on Android. No Node toolchain: front-end
libraries are vendored static files and the stylesheet is compiled with the
standalone Tailwind binary during the image build. See [ADR 7](adr/0007-web-app-fastapi-server-rendered.md).

The build stage fetches the Tailwind binary and the DaisyUI plugin from their
GitHub releases at a pinned version and checksum, and compiles `styles/app.css`
against the templates. Neither file is in the repository. The pages follow the
light or dark setting of the device.

## Users and access

- Built-in accounts: password hashes (argon2) and server-side sessions. The
  cookie holds a random token and the database only its hash.
- The first account created becomes the administrator: on a fresh instance the
  web interface asks for it. Others join by invite link.
- Forms posted from another site are refused, failed sign-ins are limited per
  email address and per client address, and pages may not be framed or cached.
- The administrator invites someone by email address. That creates the account
  without a password and a link, shown once, with which its holder sets the
  password. The same kind of link resets a lost password. A link works once
  and for 7 days.
- A user changes their own password on the Account page, which asks for the
  current one.
- The administrator can remove a user, which removes everything stored for
  them, but sees only accounts: never another user's health data.
- `user-password` on the command line sets a password, for an account made with
  `user-add` or when the administrator has lost theirs.
- Every row of user data carries a `user_id`; all queries are scoped to the
  session user.
- An instance exposed to the internet should sit behind an extra layer such as
  Cloudflare Access, but the app does not depend on it.

See [ADR 8](adr/0008-built-in-accounts-and-invites.md),
[ADR 15](adr/0015-sessions-forms-and-sign-in-limits.md) and
[ADR 16](adr/0016-invites-and-resets-as-password-links.md).

## Garmin link

1. The app shows a Garmin sign-in link. The user opens it in their own browser
   and signs in there, including MFA. The app never sees the password.
2. The user pastes the resulting address, which contains a single-use ticket,
   back into the app.
3. The app exchanges the ticket for tokens and stores them encrypted with a key
   supplied to the container (`TOKEN_ENCRYPTION_KEY`), so a database dump alone
   does not expose them.
4. The worker refreshes tokens as needed. If Garmin rejects them, the link is
   marked as needing re-linking and the user is told in the UI.

Scripted sign-in is never used: Garmin blocks it and bans the IP address.

In the browser this is the Link Garmin page, reached from the overview. The
lock that allows one sync per user is taken only for the ticket exchange, not
while the user signs in; when a sync of that user is running, linking is
refused before the ticket is spent. A user gets 5 attempts in 15 minutes, as
every attempt is a request to Garmin's sign-in site from the server's address.
`link` on the command line does the same from a terminal.

A link stays bound to the Garmin account it was first synced with. Tokens of
another account are refused before anything is fetched, so two people's data
cannot end up under one user. The encryption key can be replaced by listing
the new key before the old one until every link has been synced once.

See [ADR 9](adr/0009-garmin-client-and-token-storage.md),
[ADR 13](adr/0013-link-bound-to-one-garmin-account.md),
[ADR 14](adr/0014-token-key-rotation.md) and the
[spike findings](garmin-spike.md).

## Collection

`collect` syncs one user in this order, pausing between requests:

1. account-wide data (profile, devices, zones, records, thresholds);
2. today and yesterday, always fetched again because Garmin keeps adding to them;
3. activities in the requested period: the list, then for each new activity its
   details, laps, zones, weather and the original file;
4. older days in the period, newest first, skipping what is already stored.

Once a week per user, and on the first sync after linking, the sync is a
**catch-up**: the last 14 days are fetched again even though they are stored. A
watch that was away from its phone uploads days late, after those days were
stored as empty; the catch-up picks them up without anyone having to act. A gap
longer than 14 days needs `collect --since` by hand.

An empty answer is stored, so it is not asked for again; a failed request is
not, so the next sync retries it. A sync that is interrupted or rate-limited
keeps what it fetched and the next one continues from there. If Garmin rejects
the tokens, the link is marked as needing a new sign-in and nothing retries.
Only a 401 answer counts as a rejection: when Garmin is unreachable or busy the
link stays active and the next sync tries again.

Refreshed tokens are stored with every commit of a sync, not only at its end,
so a sync that is killed does not lose them. A PostgreSQL advisory lock allows
one sync per user at a time; a second one is skipped. A failure for one user
does not stop the sync of the others.

A scheduled worker that runs this for every linked user comes with the web
foundation; until then `collect` is run by hand or by cron.

## Data

Two layers, see [ADR 10](adr/0010-raw-payloads-plus-normalised-tables.md):

- **Raw**: every Garmin response as JSONB, keyed by user, endpoint and date.
- **Normalised**: typed tables per metric family, derived from the raw layer by
  the parsers in `normalise.py`. So far: daily summaries, sleep sessions, HRV
  summaries, and intraday samples for heart rate, stress, body battery,
  respiration, HRV and steps, plus training readiness, training status, VO2
  max, race predictions, fitness age and power thresholds, and activities
  with their laps and time in zones.
- **Original files**: the recording of each activity as downloaded from Garmin,
  in `raw_files`.

Activities are stored in full but only summarised in typed tables. A table of
per-second samples (heart rate, pace, power, position) is deliberately left for
later: the single-activity chart reads the stored details response, and the
table can be filled from the original files when analysis across activities
needs it. See [ADR 12](adr/0012-activities-stored-in-full.md).

Still raw-only, because the sample account had no data to build against: pulse
ox, endurance score, hill score, and lactate threshold heart rate and speed.
  Garmin marks unmeasured points with negative numbers; parsers drop them.

Schema changes are Alembic migrations, applied on start-up of the `web` service.

## Deployment

Reference deployment, see [ADR 11](adr/0011-compose-deployment-behind-cloudflare-tunnel.md):

- Docker Compose on a Linux host (the owner runs it in an Ubuntu VM on Proxmox).
- Configuration through a `.env` file: database password, token encryption key,
  and where the web interface listens.
- Published through an existing Cloudflare tunnel as its own hostname, with
  Cloudflare Access in front. Home Assistant can show it as a sidebar webpage
  panel but does not route or authenticate it.

## Later

- **Goals**: per-user goals (event, date, target) stored relationally.
- **AI analysis**: the Claude API reads normalised metrics and goals and writes
  recommendations; needs its own decision record (data sent, cost, consent).
