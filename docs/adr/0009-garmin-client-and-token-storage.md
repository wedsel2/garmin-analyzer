# 9. Garmin access through python-garminconnect, linked by browser sign-in, storing only encrypted tokens

- Status: Accepted (revised after the phase 2 spike, see [findings](../garmin-spike.md);
  token refresh confirmed on 2026-10-03, which settles the open point under
  Consequences; extended by [ADR 13](0013-link-bound-to-one-garmin-account.md)
  and [ADR 14](0014-token-key-rotation.md))
- Date: 2026-10-01

## Context

Garmin offers no official API for personal use. Community libraries use the same
endpoints as the Garmin Connect apps. The app holds access to several people's
health data, and the repository is public.

The spike showed that **scripted sign-in is not viable**: with
python-garminconnect 0.3.17 every login strategy was refused on the first
attempt, and two runs got the home IP address temporarily banned from Garmin's
sign-in site, browser included. A person signing in in their own browser is not
affected, and the single-use ticket that sign-in produces can be exchanged for
tokens. With tokens, all 70 probed read endpoints answered without errors.

## Decision

- Use **python-garminconnect** for token handling and data calls, behind a small
  interface of our own so it can be replaced.
- **The app never asks for or sees a Garmin password.** A user links Garmin by:
  1. opening a Garmin sign-in link shown by the app, in their own browser;
  2. signing in there, including MFA;
  3. pasting the resulting address (which contains `ticket=ST-...`) back into the app.
  The app exchanges the ticket for tokens straight away, as tickets are
  short-lived and single-use.
- Store only the tokens, encrypted with a symmetric key from the
  `TOKEN_ENCRYPTION_KEY` environment variable.
- Never run a scripted credential login, not even as a fallback.
- When tokens are rejected, mark the link as needing re-linking and show that in
  the UI. No automatic retries against the sign-in site.
- The worker rate-limits its calls and spreads users out.
- Tests never contact Garmin; they run against scrubbed, recorded fixtures.

## Alternatives considered

- **Credentials and MFA code entered in the app** (the original proposal):
  blocked by Garmin's bot protection, risks banning the server's IP address for
  all users, and puts passwords through the app.
- **Official Garmin Health API**: requires an approved business programme.
- **Importing export files**: no login fragility, but manual and missing most
  wellness metrics.
- **Automating a real browser on the server**: heavy, and still a scripted
  sign-in from the server's address.

## Consequences

- Linking takes a copy-and-paste step, which the UI has to explain well.
- A leaked database plus key exposes tokens, never passwords.
- The ticket exchange uses a private function of the library
  (`_exchange_service_ticket`) and Garmin's widget sign-in address. Either can
  change; the library version is pinned and the exchange sits behind our own
  interface with a test.
- Losing the encryption key means every user has to link again.
- Still to confirm: that tokens refresh on their own after the access token
  expires (about 26 hours). If they do not, users would need to re-link daily
  and this decision has to be revisited.
