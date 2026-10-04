# 22. A user asks for a sync on the account page and the worker runs it

- Status: Accepted
- Date: 2026-10-04

## Context

The worker syncs every linked user once per interval, an hour by default
([ADR 17](0017-worker-as-a-polling-loop.md)). Someone who has just uploaded a
run wants to see it without waiting, and until now only whoever has a shell on
the server could run `collect`. A sync takes from a minute to hours, holds a
per-user lock, and every sync is requests to Garmin from the server's address,
which Garmin bans when it sees too many.

## Decision

- The account page has a box with a button, shown when the Garmin link is
  active. Pressing it stores the time in `garmin_links.sync_requested_at` and
  nothing else: the web process still never talks to Garmin for a sync.
- The worker treats a link with a request as due without waiting for the
  interval. It does wait until five minutes have passed since that user's last
  completed sync and last attempt (`REQUEST_GAP`), or the interval when that is
  shorter.
- The worker clears the request when it starts the sync, however the sync ends.
  One press is one sync; a failed one is not repeated until the user asks again
  or the interval has passed.
- The user chooses a period: the last 3 days, week, 2 weeks or 4 weeks. It is
  stored in `garmin_links.sync_requested_days`, and the sync fetches every day
  in it again, also the days already stored. Other values are refused.
- Four weeks is the longest. A day is 18 requests, paced one per second, so
  four weeks is some 500 requests and about ten minutes, during which the
  worker syncs nobody else. Activities in the period are listed again; their
  details, fetched once, are not.
- While a request is waiting the button is disabled and a second request
  changes nothing. A user can only ask for their own data.

## Alternatives considered

- **Syncing in the web request, or in a background task of the web process**:
  the result is there sooner, but a long sync would die with a restart of
  `web`, and ADR 17 already turned this down for the scheduled sync.
- **Clearing `last_synced_at` to make the user due**: no new column, but the
  page loses when data was last collected, and the worker's memory of attempts
  would still hold the user back for an interval.
- **A limit in the web process, as for sign-in attempts**: stops repeated
  presses, but it is kept in memory per process and knows nothing of the syncs
  the worker ran. The gap in the worker covers both.
- **A queue table with one row per request**: keeps a history of requests,
  which nothing needs; one sync answers any number of presses.

## Consequences

- A requested sync starts within a minute when the worker is idle, later when
  it is busy with another user or within the gap. The page says "within a few
  minutes" and does not show progress; the user reloads to see the new time.
- A user can cause at most one sync per five minutes, and one of four weeks
  keeps the worker busy for ten. Requests to Garmin stay paced at one per
  second whatever is asked. With a handful of users that is acceptable; an
  instance with many users may need a longer gap or a shorter longest period.
- Without a running worker the request waits and the button stays disabled.
- Loading more than four weeks, or history from before the catch-up, is still
  `collect --since` on the server.
