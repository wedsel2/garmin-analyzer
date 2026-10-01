# garmin-analyzer

Collects Garmin metrics into PostgreSQL so they can be visualised and analysed.

> Status: pipeline skeleton. The image currently only provides a `healthcheck`
> command; the collector and dashboards come later.

## Run

```bash
cp .env.example .env   # then set POSTGRES_PASSWORD
docker compose run --rm app healthcheck
```

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

Details and one-time setup: [docs/ci-pipeline.md](docs/ci-pipeline.md).
Why it is built this way: [decision records](docs/adr/README.md).
