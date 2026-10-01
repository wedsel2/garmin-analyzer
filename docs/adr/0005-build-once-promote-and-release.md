# 5. Build once, promote the tested image, release with semantic-release

- Status: Accepted
- Date: 2026-10-01

## Context

Releases should be automatic, versioned and traceable to a commit, and the
released image must be exactly the one that passed scanning and smoke tests.

## Decision

- Commits follow **Conventional Commits**, enforced by a commit-msg hook.
- On every push to `main` the image is built once, scanned, smoke-tested against
  PostgreSQL via `compose.yaml`, and pushed as `sha-<commit>`.
- **semantic-release** then decides from the commit messages whether to release,
  and creates the git tag and GitHub release. It commits nothing back to the
  repository.
- A release **retags** the `sha-<commit>` image as `X.Y.Z` and `latest` (no
  rebuild), signs it with **cosign** keyless signing, and attaches a **CycloneDX
  SBOM** as an attestation and as a release asset.
- Pull requests build, scan and smoke-test, but never push.

## Alternatives considered

- **release-please**: keeps the version in `pyproject.toml` and a changelog file
  through a release pull request, but those pull requests do not trigger CI
  without a personal access token.
- **Manual tags**: simple, but easy to forget and without generated notes.
- **Rebuild on tag**: the released image would differ from the tested one.

## Consequences

- The version is not known at build time, so the image carries the commit SHA
  (`garmin-analyzer --version`, and the OCI `revision` label). The release
  version exists as the image tag and git tag; `version` in `pyproject.toml` is
  a placeholder.
- There is no `CHANGELOG.md`; release notes live on GitHub releases.
- `docs:`, `chore:` and `ci:` commits do not produce a release.
