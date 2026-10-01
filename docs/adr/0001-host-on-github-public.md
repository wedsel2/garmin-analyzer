# 1. Host on GitHub as a public repository

- Status: Accepted
- Date: 2026-10-01

## Context

The project needs free cloud hosting for source, CI and a container registry. It
started on GitLab.com Free. CI includes image builds, compose smoke tests and
scheduled jobs, which are minute-hungry. The repository holds no secrets or
personal health data by design.

## Decision

Host on GitHub Free as a public repository, with GitHub Actions for CI and GitHub
Container Registry (ghcr.io) for images.

## Alternatives considered

- **GitLab.com Free**: built-in merge request test reports and protected branches
  on private repositories, but a small monthly compute quota, no hosted Renovate,
  and dependency scanning reserved for the paid tier.
- **GitHub private repository**: more minutes than GitLab, but no enforced branch
  protection, CodeQL or secret scanning on the free plan.

## Consequences

- Unlimited Actions minutes; CodeQL, secret scanning with push protection, and
  branch rulesets are available at no cost.
- Everything in the repository and its CI logs is world-readable: Garmin tokens
  and collected data must never be committed, baked into the image, or printed in CI.
- Third-party actions are a supply-chain risk, so they are pinned by commit SHA
  and workflows default to a read-only token.
- CI is not portable; moving platforms means rewriting the workflows (the tools
  themselves carry over).
