# 3. Security and quality scanning

- Status: Accepted
- Date: 2026-10-01

## Context

We want static analysis for Python and the Containerfile, vulnerability scanning
of dependencies and the built image, secret detection, and a quality gate, all on
free tiers.

## Decision

- **SonarQube Cloud** (free plan, CI-based analysis) for code quality, coverage
  tracking and the quality gate on pull requests.
- **Trivy** scans `uv.lock` and the Containerfile on every run, and the built
  image before it is pushed. Fixable HIGH/CRITICAL findings fail the pipeline;
  image results are uploaded to GitHub code scanning.
- A **nightly Trivy scan** of the `latest` image catches CVEs published after release.
- **Hadolint** lints the Containerfile; **actionlint** lints the workflows.
- **GitHub CodeQL default setup**, **secret scanning** and **push protection** are
  enabled in repository settings rather than as workflow code. **Gitleaks** runs
  in pre-commit as the local first line.

## Alternatives considered

- **SonarQube Community Build (self-hosted)**: no pull request analysis, and a
  server to maintain.
- **Grype / Snyk**: Trivy covers lockfile, image and misconfiguration in one tool
  without an account.
- **CodeQL as a workflow file**: more control, more maintenance; default setup is
  enough for now.

## Consequences

- The SonarQube step is skipped when `SONAR_TOKEN` is absent (fork pull requests,
  or before setup), so it cannot be the only gate.
- Unfixable vulnerabilities are ignored by the gate (`ignore-unfixed`) and are
  only visible in scan output.
- CodeQL and secret scanning settings live outside the repository; they are
  listed in [the pipeline documentation](../ci-pipeline.md).
