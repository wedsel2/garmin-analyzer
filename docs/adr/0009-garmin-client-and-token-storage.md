# 9. Garmin access through python-garminconnect, storing only encrypted tokens

- Status: Proposed (to be confirmed by the phase 2 spike)
- Date: 2026-10-01

## Context

Garmin offers no official API for personal use. Community libraries use the same
endpoints as the Garmin Connect apps, authenticated with the user's own
credentials and, where enabled, MFA. These libraries break when Garmin changes
its login flow. The app holds access to several people's health data, and the
repository is public.

## Decision

- Use **python-garminconnect** behind a small interface of our own, so the
  library can be replaced without touching the collector.
- A user links Garmin by entering credentials and an MFA code once in the web
  UI. The password is used for that login only and never stored or logged.
- Store only the resulting tokens, encrypted with a symmetric key from the
  `TOKEN_ENCRYPTION_KEY` environment variable.
- When tokens are rejected, mark the link as needing re-authentication and show
  that in the UI; do not retry logins in a loop.
- The worker rate-limits its calls and spreads users out.
- Tests never contact Garmin; they run against scrubbed, recorded fixtures.

## Alternatives considered

- **Official Garmin Health API**: requires an approved business programme, not
  available to individuals.
- **Importing export files or a FIT file sync**: no login fragility, but manual
  and missing most wellness metrics.
- **Storing the Garmin password**: would allow silent re-login, at an
  unacceptable cost if the database leaks.

## Consequences

- The integration can break without warning; the app must degrade gracefully
  and tell the user.
- Losing the encryption key means every user has to link again.
- The spike must confirm: the current login and MFA flow, token lifetime and
  refresh, and which endpoints work. This record is then accepted or revised.
