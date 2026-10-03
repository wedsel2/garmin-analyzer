# 15. Sessions as hashed random tokens, forms protected by fetch metadata, sign-in limited in memory

- Status: Accepted
- Date: 2026-10-03

## Context

[ADR 8](0008-built-in-accounts-and-invites.md) chose built-in accounts with
server-side sessions, secure cookies and a rate-limited login, and left the
details open. The web interface is one process behind an optional proxy
(Cloudflare tunnel), renders its pages on the server, and uses plain forms and
HTMX. It holds health data, so a stolen database or a page on another site must
not be enough to act as a user.

## Decision

- **Sessions**: signing in creates a random 256-bit token. The browser gets it
  in a cookie; the `sessions` table stores only its SHA-256 hash. No signing
  secret is needed, so there is no `SESSION_SECRET` setting.
- **Cookie**: `HttpOnly`, `SameSite=Lax`, and `Secure` whenever the request
  arrived over HTTPS. Behind a proxy that depends on its forwarded headers being
  trusted, which is set with `FORWARDED_ALLOW_IPS`.
- **Lifetime**: a session ends 30 days after its last request, and at sign-out.
  Setting a password ends every session of that user.
- **Forms posted from another site** are refused for every method other than
  GET, HEAD and OPTIONS, by one middleware: the `Sec-Fetch-Site` header must be
  `same-origin`; without that header, `Origin` must match `Host`. A request with
  neither header is not from a browser and is let through. There are no tokens
  in forms.
- **Sign-in limit**: 5 failed attempts per email address and 20 per client
  address within 15 minutes, counted in memory. A blocked sign-in is refused
  before the password is checked. A sign-in that fails costs one argon2 check
  whether or not the account exists.
- **Passwords**: argon2id with the library defaults, 12 to 256 characters, no
  composition rules. Hashes made with older settings are replaced at sign-in.
- **Every page** carries a content security policy that allows only the app's
  own files and forbids framing, and is not cached.
- **`user-password`** on the command line sets a password for an account made
  with `user-add` and is the way back in when the administrator is locked out.

## Alternatives considered

- **Signed cookie holding the session**: no table, but a session cannot be
  ended from the server and a leaked secret forges any user.
- **Tokens in every form**: the usual protection, but each form and HTMX
  request has to carry one, and a forgotten one is a silent gap. Fetch metadata
  is sent by every current browser and is checked in one place.
- **Sign-in limit in PostgreSQL**: survives restarts and several web processes.
  There is one web process and a restart is not something an attacker can
  cause; a table can replace the counter if that changes.
- **Limit per client address only**: cannot be used to lock someone out, but
  lets a guesser with many addresses try one account without end.

## Consequences

- A database dump does not contain anything that signs a user in.
- Someone who knows a user's email address can keep them from signing in by
  failing on purpose. Accepted for a small instance that is meant to sit behind
  Cloudflare Access; sessions that are already open keep working.
- Behind a proxy whose address is not in `FORWARDED_ALLOW_IPS`, every client has
  the proxy's address, so the limit per address counts all users together, and
  the cookie is not marked `Secure`. The self-hosting guide has to say this.
- Showing the app inside another site, such as a Home Assistant panel, is not
  possible while framing is forbidden; allowing it needs a setting.
- The first account can be created by whoever reaches a fresh instance first,
  so an instance should be set up before it is published.
