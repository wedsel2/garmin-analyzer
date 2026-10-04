# 17. The worker is one process that polls the database for users due a sync

- Status: Accepted
- Date: 2026-10-04

## Context

Linked users have to be synced without anyone running `collect`. The
architecture already has a `worker` service from the same image as `web`
([ADR 6](0006-single-app-image-with-postgresql.md)). A sync of one user is safe
to interrupt and to repeat, takes one PostgreSQL advisory lock per user, and
records when it last completed. An instance has a handful of users, and Garmin
bans addresses that ask too much.

## Decision

- `garmin-analyzer worker` is a single long-running process. Once a minute it
  reads from the database which users have an active link and a last completed
  sync older than the interval (60 minutes unless `SYNC_INTERVAL_MINUTES` says
  otherwise), and syncs them one after the other with the same code as
  `collect`.
- Users who have never been synced go first, so someone who just linked is
  picked up within a minute. Their first sync is the 14-day catch-up.
- A sync that fails or stops early does not count as completed. The worker
  remembers in memory when it last tried each user and waits a full interval
  before trying again.
- Nothing is queued or scheduled outside the database. A restart only forgets
  the attempt times.
- A stop request ends the process the way Ctrl-C does: the sync in progress
  keeps what it fetched and its refreshed tokens.
- A database that is unreachable is reported and tried again a minute later.
- Statement values are left out of database error messages
  (`hide_parameters`), for every command, as the worker's output ends up in
  the container log.

## Alternatives considered

- **Cron on the host running `collect`**: nothing to build, but every
  self-hoster has to set it up, and a newly linked user waits for the next run.
- **A scheduler library (APScheduler) or a task queue (Celery, RQ)**: more
  features, but a queue needs a broker and both keep schedule state that the
  database already holds.
- **Syncing in the web process**: one service less, but a long sync would live
  and die with web requests and restarts.
- **Several users at once**: faster for many users, but more requests per
  minute to Garmin from one address.

## Consequences

- Users are synced in turn, so one long backfill delays the others. Fine for a
  handful of users.
- History older than the 14-day catch-up is still fetched by hand with
  `collect --since`.
- Only one worker should run: two would each keep their own attempt times. The
  per-user lock still prevents a double sync.
- The worker prints the email address of each user it syncs, with the number
  of requests and rows, to the container log.
- A database error message can still name the key of a row that already
  exists, since PostgreSQL writes that into the message itself.
