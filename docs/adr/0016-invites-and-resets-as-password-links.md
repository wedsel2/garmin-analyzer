# 16. An invite is an account without a password plus a single-use password link

- Status: Accepted
- Date: 2026-10-03

## Context

[ADR 8](0008-built-in-accounts-and-invites.md) decided that the administrator
invites people with single-use, expiring links and that password resets are
also links the administrator passes on, since the app sends no email. Accounts
made with `user-add` already exist without a password. The data model for
invites and resets was left open.

## Decision

- Inviting someone **creates their account straight away, without a password**,
  for the email address the administrator enters. It is the same state as an
  account made with `user-add`.
- A **password link** lets its holder set the password of one account and
  signs them in. An invite and a reset are the same thing: a link for an
  account that has no password yet, or for one that has.
- A link holds a random 256-bit token; the `password_links` table stores only
  its SHA-256 hash. It works once and for 7 days. An account has at most one
  link: making a new one replaces the old.
- The address of a link is shown to the administrator once, on the page that
  made it.
- Using a link ends every session of that account, as any password change does.
  Any password change, also with `user-password`, cancels an outstanding link.
- Only the administrator manages users: invite, new password link, remove.
  Removing a user removes everything stored for them and asks for confirmation
  first. The administrator cannot remove their own account. The page shows
  accounts and their state, never another user's Garmin link or health data.

## Alternatives considered

- **A separate invites table, with the account created when the invite is
  accepted**: the invited person could pick their own address, but invites and
  resets would be two mechanisms, and accounts from `user-add` would need a
  third.
- **The administrator sets a temporary password**: no link to keep safe, but
  the administrator knows a password of someone else, and it has to be changed
  at first sign-in.
- **Sending the link by email**: needs a mail server on every instance.

## Consequences

- One mechanism covers invites, resets and accounts made on the command line.
- The token is part of the address, so it appears in the web server's log and
  in the browser history of the person who used it. It is worthless after use
  or after 7 days, and whoever can read the server's log can already set
  passwords with `user-password`.
- The page showing a new link is the answer to a form post. Reloading it and
  confirming the browser's question makes another link, which replaces the one
  just shown.
- An invited address is taken from the moment of the invite. A mistyped
  address is corrected by removing the account and inviting again.
- The link's address is built from the request, so behind a proxy whose
  forwarded headers are not trusted it starts with `http://`.
- A lost password needs the administrator. A user who knows their password
  changes it on the Account page, which asks for the current one and counts
  wrong answers against the same limit as signing in.
