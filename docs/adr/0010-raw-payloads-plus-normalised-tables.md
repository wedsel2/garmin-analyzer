# 10. Store raw Garmin payloads plus normalised tables

- Status: Accepted
- Date: 2026-10-01

## Context

The goal is to keep all available metrics. Garmin's response formats are
undocumented and change. Charts need typed, indexed columns; later AI analysis
benefits from complete data; and re-downloading history is slow and rate-limited.

## Decision

- **Raw layer**: store each response unchanged as JSONB, keyed by user, endpoint
  and date (or activity id), with the fetch time.
- **Normalised layer**: typed tables per metric family, derived from the raw
  layer by pure functions that can be re-run.
- Access the database with **SQLAlchemy** and manage the schema with **Alembic**
  migrations, applied when the web service starts.
- Every table with user data has a `user_id` foreign key with cascading delete,
  so removing a user removes their data.

## Alternatives considered

- **Normalised tables only**: smaller, but a parsing mistake or a new field
  means downloading everything again.
- **Raw JSON only**: simple to collect, slow and awkward to chart.
- **A time-series database**: unnecessary at this volume, and goals and accounts
  are relational anyway (see ADR 6).

## Consequences

- Storage roughly doubles; still small for a handful of users.
- Adding a metric is a recipe: fixture, parser, migration, test, chart.
- Parsers are tested against fixtures, which makes Garmin format changes visible
  as failing tests once a new fixture is recorded.
