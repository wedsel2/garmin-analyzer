# 6. One application image, stock PostgreSQL alongside

- Status: Accepted
- Date: 2026-10-01

## Context

The goal is a container that collects Garmin metrics, stores them and makes them
available for visualisation, with AI-based analysis and goal management planned
later.

## Decision

Build and release a single application image (non-root, multi-stage,
`python:3.14-slim` base). Run it with `docker compose` next to the official
**PostgreSQL** image. The database connection is configured through
`DATABASE_URL`.

The application design, the Garmin client library and the visualisation layer
are deliberately undecided. The current image only provides a `healthcheck`
command, so the pipeline has something real to build and test.

## Alternatives considered

- **All-in-one image** (application, database and dashboards): harder to scan,
  upgrade and back up.
- **TimescaleDB / InfluxDB**: unnecessary for a single user's data volume; plain
  PostgreSQL also suits the relational goal data needed later.

## Consequences

- The pipeline owns one image; PostgreSQL is updated by Renovate through
  `compose.yaml`.
- The smoke test exercises the real image against a real database.
- Follow-up records are needed for the Garmin client and token storage, schema
  migrations, and visualisation.
