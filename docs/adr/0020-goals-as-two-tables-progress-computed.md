# 20. Goals are two typed tables, and progress is computed when read

- Status: Accepted
- Date: 2026-10-04

## Context

Phase 7 adds goals per user. Two kinds are in scope: an **event** to train for
(a race on a date, with a distance and a target time) and a **weekly goal**
(hours, distance or a number of activities to reach every week, for one sport
or all). The AI analysis of phase 8 will read them next to the metrics.

The two kinds share little. An event has a date and then lies in the past; a
weekly goal repeats until it is removed. Garmin tells apart many kinds of one
sport (`trail_running`, `treadmill_running`, `virtual_ride`), while a person
says "running" or "cycling". Everything progress depends on (activities,
predicted race times) is already stored and keeps changing as the collector
catches up.

## Decision

- Events live in `goal_events`, weekly goals in `weekly_goals`. Each row has a
  `user_id` that cascades, and every read and write filters on the session
  user: the goal of someone else answers 404.
- A goal names a **sport** from a short list in `goals.py`, or none. A sport
  matches an activity when Garmin's type of it contains one of the words listed
  for the sport. No sport means all activities for a weekly goal.
- **Nothing about progress is stored.** A page works out, when asked: the sum
  of this week and of the 8 weeks before for a weekly goal; Garmin's latest
  predicted time for a running event of 5 km, 10 km, a half or a whole marathon
  (within 1 %); and for a past event the longest activity of its sport that
  began that day.
- A week runs from Monday to Sunday and an activity counts on the day it began
  in UTC, as on the training page.
- Earlier weeks are held against the target as it is now. Changing a goal
  changes how its past reads; removing a goal deletes the row.
- A user has at most 50 goals of each kind. Forms are parsed in `goals.py`,
  which refuses what it cannot use with a sentence for the page.
- Goals have pages only. The JSON API gets them when a chart or another client
  needs them.

## Alternatives considered

- **One `goals` table with a kind and nullable columns, or a JSON column**: one
  list to query, but most columns would be empty for either kind, the database
  could not say which belong together, and the two kinds are shown and judged
  in different ways anyway.
- **Storing progress per week**: keeps history when a target changes, but has
  to be recomputed whenever a late upload or a catch-up changes the activities.
  The sums are cheap: one query over nine weeks of activities.
- **Garmin's exact activity type as the sport**: no list to maintain, but a
  goal for running would miss trail runs and treadmill runs.
- **A target on any collected metric** (VO2 max, resting heart rate): left out
  of this phase by choice. It would be a third table reading through the
  registry of daily metrics (ADR 18).

## Consequences

- A late upload, a catch-up or a corrected activity shows in the goals without
  anything to repair.
- There is no record of what a weekly target was in the past. If the AI
  analysis needs that, targets get a start date and are ended instead of
  changed.
- The list of sports and their words is ours to maintain. A type of activity
  that Garmin names without any of the words counts for no sport, only for
  goals over all sports.
- For someone far from UTC an activity late on Sunday or early on Monday can
  count in the neighbouring week, as it already does on the training page.
