# Architecture Decision Records

One file per decision, numbered in order. A record is not edited after acceptance
except to change its status; a changed decision gets a new record that supersedes
the old one.

| # | Decision | Status |
|---|---|---|
| [1](0001-host-on-github-public.md) | Host on GitHub as a public repository | Accepted |
| [2](0002-python-toolchain.md) | Python toolchain: uv, Ruff, mypy, pytest | Accepted |
| [3](0003-security-and-quality-scanning.md) | Security and quality scanning | Accepted |
| [4](0004-dependency-updates-with-renovate.md) | Renovate for updates, Dependabot for alerts only | Accepted |
| [5](0005-build-once-promote-and-release.md) | Build once, promote the tested image, release with semantic-release | Accepted |
| [6](0006-single-app-image-with-postgresql.md) | One application image, stock PostgreSQL alongside | Accepted |
| [7](0007-web-app-fastapi-server-rendered.md) | Custom web app: FastAPI with a server-rendered interface | Accepted |
| [8](0008-built-in-accounts-and-invites.md) | Built-in accounts with invite links | Accepted |
| [9](0009-garmin-client-and-token-storage.md) | Garmin access through python-garminconnect, linked by browser sign-in, storing only encrypted tokens | Accepted |
| [10](0010-raw-payloads-plus-normalised-tables.md) | Store raw Garmin payloads plus normalised tables | Accepted |
| [11](0011-compose-deployment-behind-cloudflare-tunnel.md) | Deploy with Docker Compose, publish through a Cloudflare tunnel | Accepted |
| [12](0012-activities-stored-in-full.md) | Store activities in full, normalise summaries, laps and zones | Accepted |
| [13](0013-link-bound-to-one-garmin-account.md) | A link stays bound to the Garmin account it was first used with | Accepted |
| [14](0014-token-key-rotation.md) | The token encryption key can be replaced without linking again | Accepted |
| [15](0015-sessions-forms-and-sign-in-limits.md) | Sessions as hashed random tokens, forms protected by fetch metadata, sign-in limited in memory | Accepted |
| [16](0016-invites-and-resets-as-password-links.md) | An invite is an account without a password plus a single-use password link | Accepted |
| [17](0017-worker-as-a-polling-loop.md) | The worker is one process that polls the database for users due a sync | Accepted |
| [18](0018-series-api-for-charts.md) | Charts read a versioned JSON API that returns series as columns | Accepted |
| [19](0019-chart-library-fetched-in-the-image-build.md) | The chart library is fetched in the image build, not committed | Accepted |
| [20](0020-goals-as-two-tables-progress-computed.md) | Goals are two typed tables, and progress is computed when read | Accepted |
| [21](0021-coach-reports-by-claude-opt-in.md) | The coach is a report that Claude writes on request, opt-in per user | Accepted |

New records use the same sections: Context, Decision, Alternatives considered,
Consequences.
