# garmin-analyzer

Self-hosted, multi-user web app that collects Garmin metrics into PostgreSQL and
visualises them. Planned later: goals and AI-based training recommendations.

Read before designing anything:

- `docs/architecture.md` - components, data flow, deployment
- `docs/roadmap.md` - phases and what is in scope now
- `docs/adr/` - why things are the way they are
- `docs/ci-pipeline.md` - pipeline, gates, releasing

## Commands

```bash
uv sync                          # set up the environment
uv run pytest                    # tests with coverage (80% floor); needs Docker running
uv run ruff check . && uv run ruff format .
uv run mypy
uvx pre-commit run --all-files   # everything CI lint runs
docker compose build && scripts/smoke-test.sh
```

Tests start a throwaway PostgreSQL through testcontainers, using the image from
`compose.yaml`.

New migration, after changing `src/garmin_analyzer/models.py` (needs
`DATABASE_URL` pointing at a database migrated to the current head):

```bash
uv run alembic revision --autogenerate -m "describe the change"
```

Review the generated file: drop enum types in `downgrade`, and name constraints.
`tests/test_migrate.py` fails if models and migrations disagree.

## Workflow

- `main` is protected. Work on a branch, open a pull request, squash-merge.
- Commit messages and PR titles follow Conventional Commits. `feat:` and `fix:`
  trigger a release; `docs:`, `ci:`, `chore:`, `test:`, `refactor:` do not.
- Add dependencies with `uv add` (or `uv add --dev`), never by editing the lockfile.
- Pin GitHub Actions by commit SHA with the version in a trailing comment.

## Pull requests

Before telling the user a pull request is ready to merge:

1. Run `/code-review` on the branch and fix or report what it finds.
2. Run `/security-review` when the change touches authentication, sessions,
   tokens, encryption, user input, the Garmin wrapper, the Containerfile or the
   workflows. Skip it for documentation-only changes and say that you skipped it.
3. Turn on Auto-fix for the pull request when the session offers it (the Claude
   desktop app does), so failing checks come back to the session. Never turn on
   auto-merge unless the user asks.
4. In the summary to the user, say which of these ran and what they found.

## Rules

- **Never run a scripted Garmin sign-in**, anywhere. It gets the IP address banned;
  accounts are linked by browser sign-in and ticket exchange (ADR 9).
- **Only `garmin.py` imports the Garmin library.** Other code goes through
  `GarminSession`, which exposes read methods only and never takes credentials.
- **Never call Garmin from tests or CI.** Tests use synthetic fixtures in
  `tests/fixtures/garmin/`, made from a local sample with
  `uv run scripts/scrub_fixture.py <endpoint>`. It keeps structure and formats
  but replaces every value. Never copy a real response into the repository, and
  review the text values the script reports as kept before committing.
  The script also writes `.garmin-tokens/stats/<endpoint>.json` with the range and
  distinct codes of each number series; read that, not the samples, to learn
  units, codes and "not measured" sentinels such as -1 and -2.
- **This repository is public.** Never commit or log Garmin credentials, tokens,
  `.env`, or real health data. `.garmin-tokens/` is local only.
- **Every table that holds user data has a `user_id`**, and every query filters on it.
- **Schema changes go through an Alembic migration**, never ad-hoc DDL.
- **The server side is Python only.** No Node toolchain; front-end libraries are
  vendored static files (see ADR 7).
- **An architecture decision needs a record.** Use the `adr` skill, and update
  `docs/architecture.md` in the same pull request when the design changes.
- Code is typed (mypy strict) and new behaviour comes with tests.
