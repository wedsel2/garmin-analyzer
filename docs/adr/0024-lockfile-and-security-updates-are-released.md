# 24. Lockfile maintenance and security updates are committed as fixes and released

- Status: Accepted
- Date: 2026-11-26

## Context

[ADR 4](0004-dependency-updates-with-renovate.md) and
[ADR 23](0023-renovate-runs-all-monday-and-tracks-tool-versions.md) expect
production dependency updates to be committed as `fix(deps)`, so that they
produce a patch release and reach the published image. Renovate's semantic
commit preset only does that for direct dependencies. Lockfile maintenance, and
security updates that only change `uv.lock` (transitive packages), are committed
as `chore(deps)`, which semantic-release ignores.

On 25 November the nightly scan of `latest` (v1.23.2, built 10 November) failed
on CVE-2026-126360 in `opentelemetry-api` 1.45.1, a transitive package. `main`
had carried the fixed 1.45.2 since lockfile maintenance on 11 November, but that
was a `chore` commit, so no image with the fix had been released. CI scans the
image it builds for each change, but users run the released one.

## Decision

- Renovate commits lockfile maintenance as `fix(deps)` (`lockFileMaintenance`
  `semanticCommitType: fix`).
- Renovate commits updates raised by a vulnerability alert as `fix(deps)`
  (`vulnerabilityAlerts` `semanticCommitType: fix`), whatever the dependency
  type.
- Other updates keep the types ADR 4 describes: `fix(deps)` for production
  dependencies, `chore(deps)` for actions, hooks, development dependencies and
  build tools.

## Alternatives considered

- **Rebuild and re-release on a schedule**: keeps the image fresh without a
  commit, but semantic-release only releases from commits, and a release without
  a commit breaks build-once-promote (ADR 5).
- **Release only when a lockfile change touches a runtime package**: precise,
  but needs a custom check of `uv export --no-dev` before and after, which
  Renovate cannot express in its commit type.
- **Leave it to the nightly scan**: it reports the problem, but someone then has
  to cut a release by hand, as happened here.

## Consequences

- A lockfile fix reaches a release the Monday it is merged, and every release
  also rebuilds the image on current Debian packages.
- Weekly lockfile maintenance produces a patch release even when only
  development packages changed; the image is then the same apart from OS
  updates. At most one such release a week.
- The nightly scan should now fail only for a CVE published since the last
  release, not for one already fixed on `main`.
