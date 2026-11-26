# CI/CD pipeline

How the pipeline works and what has to be configured outside the repository.
The reasoning behind each choice is in the [decision records](adr/README.md).

## Flow

```text
pull request / push to main
 ├─ lint          pre-commit: Ruff, mypy, Hadolint, actionlint, lockfile check,
 │               pinned download checksums
 ├─ test          pytest + coverage → SonarQube Cloud
 └─ scan-source   Trivy on uv.lock and Containerfile
        │ all three must pass
        ▼
    image         build → Trivy image scan → smoke test → push sha-<commit> (main only)
        │ main only
        ▼
    release       semantic-release → retag X.Y.Z + latest → cosign sign → SBOM

nightly           Trivy rescan of the latest released image
mondays           Renovate update pull requests (hosted app, not a workflow)
```

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | Lint, test, scan, build, smoke test, release |
| `.github/workflows/nightly-scan.yml` | Nightly vulnerability rescan of `latest` |
| `.pre-commit-config.yaml` | Hooks shared by local commits and the lint job |
| `scripts/smoke-test.sh` | Smoke test, runnable locally and in CI |
| `scripts/check_pinned_downloads.py` | Checks the Containerfile's pinned downloads against their checksums |
| `renovate.json` | Dependency update policy |
| `.releaserc.json` | semantic-release configuration |
| `sonar-project.properties` | SonarQube Cloud project settings |

## Gates

A change cannot reach the registry unless:

- all pre-commit hooks pass, including the check that every file the
  Containerfile downloads matches its `--checksum` for the version in its `ARG`
  ([ADR 25](adr/0025-pinned-downloads-checked-in-lint.md)),
- tests pass with at least 80% coverage,
- the SonarQube Cloud quality gate passes (`sonar.qualitygate.wait=true`),
- Trivy finds no fixable HIGH or CRITICAL vulnerability in the lockfile,
  Containerfile or image,
- the image runs as non-root, applies its migrations to a fresh PostgreSQL,
  passes `healthcheck` afterwards, serves the sign-in page and the compiled
  stylesheet,
  and fails `healthcheck` before migrating and when the database is down.

## Releasing

Releases are driven by commit messages on `main`:

| Commit type | Result |
|---|---|
| `fix: ...` | Patch release |
| `feat: ...` | Minor release |
| `feat!: ...` or a `BREAKING CHANGE:` footer | Major release |
| `docs:`, `chore:`, `ci:`, `test:`, `refactor:` | No release |

Verify a released image:

```bash
cosign verify ghcr.io/wedsel2/garmin-analyzer:<version> \
  --certificate-identity-regexp '^https://github.com/wedsel2/garmin-analyzer/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Updating a pinned download

Renovate raises `TAILWIND_VERSION`, `DAISYUI_VERSION`, `ECHARTS_VERSION` and
`HTMX_VERSION` in the Containerfile but cannot change the checksums, so these
pull requests are not merged automatically. On such a pull request the `lint`
job fails with the sha256 of each new file; put it in the matching
`--checksum`, or run the check locally:

```bash
uv run scripts/check_pinned_downloads.py
```

The check downloads every file without a cache. A green image build alone does
not prove the checksums are right: BuildKit reuses a cached `ADD` layer with
the same checksum without fetching the new URL.

## One-time setup outside the repository

These settings are not stored in the repository and must be redone if it is recreated.

1. **SonarQube Cloud**: import the repository, switch the analysis method from
   Automatic Analysis to CI-based, and add the token as the `SONAR_TOKEN`
   Actions secret. Check that the organization and project key match
   `sonar-project.properties`.
2. **Renovate**: install the Mend Renovate GitHub App on the repository.
3. **Security settings** (Settings → Advanced Security): enable Dependabot
   alerts, CodeQL default setup, secret scanning and push protection. Leave
   Dependabot version and security updates off.
4. **Branch ruleset for `main`**: require a pull request and the status checks
   `lint`, `test`, `scan-source` and `image`; block force pushes.
5. **Merging**: allow squash merging with the pull request title as the commit
   message, so the Conventional Commit type decides the release. Enable
   auto-merge for Renovate.
6. **Package visibility**: after the first push, set the `garmin-analyzer`
   package on ghcr.io to public.

## Local use

```bash
uv sync
uvx pre-commit install
uv run pytest
docker compose build
scripts/smoke-test.sh
```
