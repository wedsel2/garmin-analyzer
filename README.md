# garmin-analyzer

Collects Garmin metrics into PostgreSQL so they can be visualised and analysed.

> Status: the collector runs from the command line. The web interface and
> dashboards come next.

## Run

```bash
cp .env.example .env                                  # set POSTGRES_PASSWORD
docker compose run --rm app generate-key              # put the result in .env as TOKEN_ENCRYPTION_KEY
docker compose run --rm app migrate
docker compose run --rm app user-add you@example.com
docker compose run --rm app link you@example.com      # sign in to Garmin in your browser, paste the address
docker compose run --rm app collect --days 7
```

`collect` without an email syncs every linked user. Run it again at any time: it
fetches the last two days anew and only what is still missing before that. Once
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

- [Architecture](docs/architecture.md) and [roadmap](docs/roadmap.md)
- Contributing with Claude Code: [CLAUDE.md](CLAUDE.md) and `.claude/` hold the
  shared project instructions, permissions and skills.

Details and one-time setup: [docs/ci-pipeline.md](docs/ci-pipeline.md).
Why it is built this way: [decision records](docs/adr/README.md).
