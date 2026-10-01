# 8. Built-in accounts with invite links

- Status: Accepted
- Date: 2026-10-01

## Context

An instance serves its owner and a handful of friends. Each user has their own
Garmin link and must only see their own data. Setting up a user should be easy,
and other people should be able to self-host an instance without extra
infrastructure.

## Decision

- The app manages its own accounts: email, argon2 password hash, server-side
  sessions in PostgreSQL, secure cookies.
- The first account registered on a fresh instance becomes the administrator.
  Registration is closed after that.
- The administrator creates single-use, expiring **invite links**; the invited
  person chooses a password and then links Garmin.
- Authorisation is by ownership: every row of user data has a `user_id` and
  every query is scoped to the session user. Administrators manage accounts but
  do not see other users' health data.
- Login is rate-limited.

## Alternatives considered

- **External identity provider (OIDC, for example Authentik or Keycloak)**:
  stronger features, but a heavy prerequisite for self-hosters.
- **Trusting Cloudflare Access identity headers**: no password handling, but ties
  every instance to Cloudflare and breaks local access.
- **Home Assistant users through add-on ingress**: only works on Home Assistant
  OS and couples the app to it.
- **Open self-registration**: unsuitable for an instance reachable from the
  internet.

## Consequences

- We own password and session security, so it needs careful tests and review.
- No email is sent: invites and password resets are links the administrator
  passes on.
- OIDC login can be added later next to local accounts without changing the
  data model.
