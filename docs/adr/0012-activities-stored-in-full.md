# 12. Store activities in full, normalise summaries, laps and zones

- Status: Accepted
- Date: 2026-10-02

## Context

Activities are the largest Garmin responses: the details of one activity, with
time series and GPS track, are about 900 kB of JSON. That response is not the
full recording, because the library asks Garmin for at most 2,000 chart points
and 4,000 track points by default, so long activities arrive downsampled. The
complete per-second recording is the original file from the device (FIT), which
can be downloaded per activity; a test download returned a 64 kB archive
holding a 136 kB FIT file.

Reducing what we store would make it hard to rebuild data later. Normalising
every sample costs one to two million rows per user per year, and nothing needs
them yet.

## Decision

- Store every activity response unchanged in `raw_payloads`: summary, details,
  laps and splits, time in zones, weather and exercise sets.
- Also store the **original activity file** as downloaded, in a table for binary
  files (`raw_files`). It is the source of truth for the recording.
- Normalise into typed tables now:
  - `activities`: one row per activity with its summary figures;
  - `activity_laps`: laps;
  - `activity_zones`: time in each heart rate and power zone.
- Do **not** create a table of per-second samples yet. The chart of a single
  activity is drawn from the stored details response.

## Alternatives considered

- **Store only summaries and laps**: small, but the recording could only be
  recovered by downloading again, and only while Garmin keeps it.
- **Rely on the details response alone**: loses resolution on long activities.
- **Normalise all samples now**: large tables and a migration burden before any
  feature uses them.
- **Parse FIT files instead of the JSON responses**: a second parser and a new
  dependency for the same summary figures Garmin already computes.

## Consequences

- Nothing is lost: a samples table can be filled later from the stored files
  when analysis across activities needs it, such as a power curve or time at
  pace over a season. That will need its own record and a FIT parser.
- Storage is dominated by activities: roughly 1 MB of raw JSON plus the original
  file per activity, before PostgreSQL compression.
- Collecting one activity takes about six requests, so backfilling history is
  paced: the activity list first, details afterwards.
- GPS tracks are the most sensitive data in the system. They exist only in the
  instance database; fixtures never contain real coordinates.
