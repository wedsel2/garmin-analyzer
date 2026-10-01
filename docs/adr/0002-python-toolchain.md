# 2. Python toolchain: uv, Ruff, mypy, pytest

- Status: Accepted
- Date: 2026-10-01

## Context

The project needs dependency management with a reproducible lockfile, linting,
formatting, type checking and tests, running identically locally, in pre-commit
and in CI.

## Decision

- **uv** manages dependencies, the lockfile (`uv.lock`), the virtual environment
  and the Python version (`.python-version`). CI and the image build use
  `--locked`, so a stale lockfile fails.
- **Ruff** for linting and formatting, including the bandit-derived `S` security rules.
- **mypy** in strict mode.
- **pytest** with branch coverage and an 80% floor; coverage and JUnit XML feed
  SonarQube Cloud.
- **pre-commit** runs the same checks locally and in the CI lint job, plus
  Hadolint, actionlint, Gitleaks and a Conventional Commits message check.

## Alternatives considered

- **Poetry / pip-tools**: slower, and need a separate tool for Python version management.
- **flake8 + black + isort + bandit**: four tools and configs for what Ruff does in one.
- **pyright**: equally valid; mypy was chosen as the more common default.

## Consequences

- One command (`uv sync`) sets up a working environment.
- mypy runs as a local hook through `uv run`, so it needs the project environment
  (CI runs `uv sync` first).
- Tests must never call Garmin live; API interactions will be tested against
  recorded fixtures.
