# 4. Renovate for updates, Dependabot for alerts only

- Status: Accepted
- Date: 2026-10-01

## Context

Dependencies live in several places: `uv.lock`, container base images, compose
images, GitHub Actions pinned by SHA, pre-commit hooks, and tool versions inside
workflows. Both Renovate and Dependabot can open update pull requests.

## Decision

Use the hosted **Mend Renovate app** for all update pull requests. Enable
**Dependabot alerts** only; leave Dependabot version and security updates off.

Renovate configuration (`renovate.json`): `config:best-practices` (digest-pins
images and actions), a weekly schedule, a 3-day minimum release age, weekly
lockfile maintenance, and automerge for non-major updates once CI is green.
Major updates wait for review.

## Alternatives considered

- **Dependabot version updates**: built in, but no digest pinning of base images,
  no custom version rules, automerge needs a hand-written workflow, and its pull
  requests run with a separate, restricted secret set.
- **Both bots opening pull requests**: duplicates.

## Consequences

- Renovate reads Dependabot alerts and raises security fixes immediately,
  bypassing the schedule.
- Automerge relies on the CI pipeline being a trustworthy gate; the release-age
  delay limits exposure to freshly compromised packages.
- Production dependency updates are committed as `fix(deps)` and therefore
  produce patch releases.
