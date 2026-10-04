# 18. Charts read a versioned JSON API that returns series as columns

- Status: Accepted
- Date: 2026-10-04

## Context

ADR 7 says charts are fed by a JSON API that a native client could use later.
The dashboards need many daily series (sleep score, resting heart rate, load)
over a range of dates, several of them per page. The data is health data, so an
answer must never hold another user's rows, and the pages allow scripts and
requests to the same origin only.

## Decision

- The API lives under `/api/v1`. A change that breaks a client gets a new prefix.
- It is authenticated by the same session cookie as the pages. Without a session
  it answers 401, not a redirect. Every query filters on the session user; a
  request cannot name a user.
- A **daily metric** is a number column of a table with a `calendar_date`. The
  metrics are listed in one registry, `metrics.py`, with their label, unit and
  whether higher is better. Pages and the API both read through it.
- `GET /api/v1/daily?start=&end=&metrics=a,b` returns `dates` and, per metric, a
  list of the same length, with `null` for a day without a value. A metric not
  in the registry is refused, so a request cannot reach other columns.
- A range is at most 3660 days.
- The OpenAPI description is served at `/api/v1/openapi.json` and lists the API
  only. The interactive documentation pages stay off: they load scripts from
  another site, which the content security policy forbids.
- The page renders the numbers; the script fetches only what a chart draws.

## Alternatives considered

- **Chart data embedded in the page**: one request less, but no interface for
  another client, and changing the range would mean rendering the page again.
- **One endpoint per metric family**: simpler to describe each, but an overview
  that combines families would need a request per tile.
- **Rows as objects (`[{date, steps, ...}]`)**: familiar, but larger, and the
  chart library wants columns anyway.
- **Tokens for the API**: needed by a native client, not by the pages. Added
  when such a client exists.

## Consequences

- A new daily metric is one line in the registry.
- Intraday samples and activities need their own endpoints, with bucketing on
  the server; they follow the same rules.
- The cookie is `SameSite=Lax` and the API only reads, so another site cannot
  read an answer or change anything through it.
