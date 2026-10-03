# 13. A link stays bound to the Garmin account it was first used with

- Status: Accepted
- Date: 2026-10-03

## Context

A user links Garmin by signing in in their own browser and pasting the ticket
(see [ADR 9](0009-garmin-client-and-token-storage.md)). Nothing stopped a user
from linking again with a different Garmin account, by mistake or on purpose.
The next sync would then store that account's data under the same `user_id`,
mixed with what was already there. Raw payloads and normalised rows carry no
mark of the Garmin account they came from, so the mix cannot be undone.

Linking makes no request beyond the ticket exchange, on purpose: a second
request could fail and throw away tokens that were just obtained. The Garmin
account is therefore not known at the moment of linking. It is known as soon as
a session is resumed from tokens, because the library loads the profile then.

## Decision

- `garmin_links.garmin_account_id` holds Garmin's number for the account
  (`profileId`). It is empty after linking and set the first time the link is
  opened for a sync.
- Opening a link compares the account of the tokens with the one on record. If
  they differ, nothing is fetched, the link is marked as needing a new sign-in
  and the error says to link the original account again.
- Linking again keeps the account on record.
- A sync and a link of the same user exclude each other through the per-user
  advisory lock, so a sync that is ending cannot store its old tokens over
  freshly linked ones. `link` checks this before asking the user to sign in.

## Alternatives considered

- **Read the profile while linking**: gives feedback at once, but adds a
  request that can fail after the single-use ticket is spent.
- **Tag every row with the Garmin account**: allows several accounts per user,
  which nobody needs, and touches every table and query.
- **Leave it to the user**: a single mistake corrupts the data for good.

## Consequences

- A wrong account is reported at the first sync after linking, not while linking.
- Moving a user to another Garmin account is not supported: it needs a new user,
  or a future command that deletes the stored data first.
- Links that exist already get their account recorded at their next sync.
