# 14. The token encryption key can be replaced without linking again

- Status: Accepted
- Date: 2026-10-03

## Context

Garmin tokens are stored encrypted with the key in `TOKEN_ENCRYPTION_KEY`
(see [ADR 9](0009-garmin-client-and-token-storage.md)). With a single key,
replacing it, for example after it may have leaked, made every stored token
unreadable, and every user had to sign in to Garmin again.

## Decision

- `TOKEN_ENCRYPTION_KEY` may hold several keys separated by commas. The first
  one encrypts; all of them are tried when decrypting.
- When a link is opened and its tokens are not encrypted with the first key,
  they are stored again with it.
- To replace the key: put the new key first and the old one after it, run
  `collect` for every user, then remove the old key.

## Alternatives considered

- **A separate re-encrypt command**: one more thing to run and document, while
  every sync already reads and writes the tokens.
- **A key identifier stored with each link**: needed for many keys, not for
  replacing one.

## Consequences

- Still symmetric encryption with Fernet from the `cryptography` library; no
  change to what a leaked database or a leaked key exposes.
- A link that is not synced during the rotation, such as one that needs a new
  sign-in, stays on the old key. Removing the old key makes its tokens
  unreadable, which only matters if that link would have worked again.
