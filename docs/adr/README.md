# Architecture Decision Records

One file per decision, numbered in order. A record is not edited after acceptance
except to change its status; a changed decision gets a new record that supersedes
the old one.

| # | Decision | Status |
|---|---|---|
| [1](0001-host-on-github-public.md) | Host on GitHub as a public repository | Accepted |
| [2](0002-python-toolchain.md) | Python toolchain: uv, Ruff, mypy, pytest | Accepted |
| [3](0003-security-and-quality-scanning.md) | Security and quality scanning | Accepted |
| [4](0004-dependency-updates-with-renovate.md) | Renovate for updates, Dependabot for alerts only | Accepted |
| [5](0005-build-once-promote-and-release.md) | Build once, promote the tested image, release with semantic-release | Accepted |
| [6](0006-single-app-image-with-postgresql.md) | One application image, stock PostgreSQL alongside | Accepted |

New records use the same sections: Context, Decision, Alternatives considered,
Consequences.
