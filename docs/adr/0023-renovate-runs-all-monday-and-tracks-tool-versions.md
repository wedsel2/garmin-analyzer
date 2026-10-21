# 23. Renovate runs all of Monday, also checks OSV, and tracks tool versions set in workflows

- Status: Accepted
- Date: 2026-10-21

## Context

[ADR 4](0004-dependency-updates-with-renovate.md) chose the hosted Mend Renovate
app for update pull requests, with Dependabot alerts only, on a weekly schedule
of Monday before 6am. Three weeks in, two gaps showed:

- The hosted app does not run at a fixed time. It did not run between Saturday
  17 and Wednesday 21 October, so the Monday window was missed and a week of
  updates waited. Lockfile maintenance has an even narrower default window,
  before 4am on Monday.
- `trivy-action` installs its own default Trivy (v0.70.0) when no `version` is
  given. Renovate only sees the action's pin, so the scanner fell six releases
  behind without a pull request.

On the same day, the nightly scan found a critical CVE in `certifi`, a
transitive package in `uv.lock`, and no Dependabot alert or Renovate pull
request had raised it.

## Decision

ADR 4 stands, with these changes:

- The update schedule and the lockfile maintenance schedule are all of Monday
  (`on monday`, Europe/Amsterdam), not a few early hours.
- Renovate also checks the dependencies it detects against OSV
  (`osvVulnerabilityAlerts`), next to Dependabot alerts.
- A tool version that an action would otherwise pick itself is set in the
  workflow `env` as `<NAME>_VERSION` with a `# renovate:` comment, which the
  `customManagers:githubActionsVersions` preset reads. Trivy is the first:
  `TRIVY_VERSION`, used by every `trivy-action` step.

## Alternatives considered

- **Several windows a week, or no schedule**: more pull requests and CI runs
  for a solo project, and the release-age delay already decides when an update
  is ready. One day a week with room for the app's timing is enough.
- **A self-hosted Renovate workflow on a cron**: runs at a known time, but
  needs a token with write access to the repository, and is one more workflow
  to maintain instead of a hosted app.
- **Pinning Trivy without a Renovate comment**: the same drift, only later.

## Consequences

- An update window is missed only if the app does not run at all on a Monday;
  the Dependency Dashboard can still start a run by hand.
- OSV and Dependabot cover the packages they detect. Renovate detects the
  direct dependencies in `pyproject.toml`, not transitive packages in `uv.lock`;
  Dependabot does see those, but only alerts on advisories GitHub has reviewed.
  A vulnerable transitive package can wait for the weekly lockfile maintenance,
  and the nightly scan is what reports it.
- `osvVulnerabilityAlerts` is marked experimental in Renovate; if it misbehaves,
  turning it off returns to ADR 4's alerts.
- Production dependency updates are still committed as `fix(deps)` and produce
  patch releases.
