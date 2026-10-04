# garmin-analyzer

Collects Garmin metrics into PostgreSQL so they can be visualised and analysed.

> Status: accounts, invites, linking Garmin, automatic collection and the
> dashboards and goals work, the site can be installed as an app on Android,
> and a coach (Claude) writes reports for users who turn it on; see the
> [roadmap](docs/roadmap.md).

To run your own instance from a released image, and to publish it, follow the
[self-hosting guide](docs/self-hosting.md). What follows is the short version,
from a checkout.

## Run

```bash
cp .env.example .env                                  # set POSTGRES_PASSWORD
docker compose build                                  # or set APP_IMAGE in .env to a released image
docker compose run --rm --no-deps web generate-key    # put the result in .env as TOKEN_ENCRYPTION_KEY
docker compose up --detach                            # applies migrations, serves http://localhost:8000, starts the worker
```

Open <http://localhost:8000> and create the administrator account. Do this
before making the instance reachable by others: whoever opens a fresh instance
first becomes its administrator. Choose **Link Garmin** on the overview: you
sign in at Garmin in your own browser and paste the resulting address back.
The worker picks up a new link within a minute, fetches the last two weeks,
and from then on syncs every linked user once an hour. To fetch older history:

```bash
docker compose run --rm web collect you@example.com --since 2024-01-01
```

Invite others from the Users page: it shows a link to pass on, with which they
choose their password. The same page makes a new link for someone who lost
their password and removes users. Everyone changes their own name, email
address and password on the Account page. `user-password <email>` on the command line sets a password when
you have lost your own.

After updating the image, `docker compose up --detach` applies new migrations.
The other commands refuse to run until that, or `migrate`, has been done.

`collect` without an email syncs every linked user, as the worker does. Run it
at any time: it fetches the last two days anew and only what is still missing before that. Once
a week it also fetches the last two weeks again, so days your watch uploaded
late are not missed. Use `--since 2024-01-01` to fill in history; it can be
interrupted and resumed.

A user stays linked to the Garmin account of their first sync; linking another
account is refused at the next `collect`. To replace `TOKEN_ENCRYPTION_KEY`
without everyone signing in again, see the note in `.env.example`.

Released images: `ghcr.io/wedsel2/garmin-analyzer:<version>`.

## Develop

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
uv sync
uvx pre-commit install
uv run pytest
docker compose build && scripts/smoke-test.sh
```

The stylesheet is compiled and the chart library fetched in the image build. To
see styled pages with charts from `uv run garmin-analyzer serve`, run
`scripts/build-static.sh` once and again after changing a template; it writes
the git-ignored `static/app.css`, `static/echarts.min.js` and
`static/htmx.min.js`.

Commits follow [Conventional Commits](https://www.conventionalcommits.org/):
`fix:` produces a patch release, `feat:` a minor one.

## Pipeline

| Stage | What runs |
|---|---|
| Lint | pre-commit: Ruff, mypy, Hadolint, actionlint, lockfile check |
| Test | pytest with coverage, SonarQube Cloud analysis |
| Scan source | Trivy on `uv.lock` and the Containerfile |
| Image | Build, Trivy image scan, smoke test against PostgreSQL, push `sha-<commit>` |
| Release | semantic-release tags the commit; the tested image is retagged, signed with cosign and gets a CycloneDX SBOM |
| Nightly | Trivy rescan of the `latest` image |

Dependencies (Python, base images, actions, pre-commit hooks) are kept current by Renovate.

## Documentation

- [Self-hosting guide](docs/self-hosting.md)
- [Architecture](docs/architecture.md) and [roadmap](docs/roadmap.md)
- Contributing with Claude Code: [CLAUDE.md](CLAUDE.md) and `.claude/` hold the
  shared project instructions, permissions and skills.

Details and one-time setup: [docs/ci-pipeline.md](docs/ci-pipeline.md).
Why it is built this way: [decision records](docs/adr/README.md).
