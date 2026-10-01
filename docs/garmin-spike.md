# Garmin spike findings

Phase 2 of the [roadmap](roadmap.md). Run on 2026-10-01 with
python-garminconnect 0.3.17 against one real account, using
`scripts/garmin_spike.py`. Only response shapes were inspected, not values.

## Login

| Finding | Detail |
|---|---|
| Scripted sign-in is blocked | All five library strategies were refused (HTTP 429 or a Cloudflare challenge) on the very first attempt. |
| It gets the IP address banned | After two runs, Garmin's sign-in site returned Cloudflare error 1015 to the whole home IP address, including a normal browser. The ban lifted within about two hours. |
| Browser sign-in plus ticket exchange works | The user signs in at Garmin's widget sign-in address; the final address contains `ticket=ST-...`; exchanging that ticket yields tokens. |
| Tokens | Three fields: `di_token` (access token, valid about 26 hours), `di_refresh_token` (opaque) and `di_client_id`. They serialise to a JSON string, so they can be stored encrypted in the database. |
| Not yet confirmed | Automatic refresh once the access token has expired. |

Consequence: the app links accounts by browser sign-in and never handles Garmin
passwords. See [ADR 9](adr/0009-garmin-client-and-token-storage.md).

## Endpoints

70 read-only calls: 65 returned data, 5 were empty for this account, none failed.
Calls take 0.1 to 0.3 seconds each.

### Daily wellness (one call per day)

| Family | Call | Notes |
|---|---|---|
| Daily summary | `get_user_summary` | 91 fields: calories, steps, distance, floors, stress, body battery, heart rate. `get_stats_and_body` adds body composition (102 fields). |
| Steps | `get_steps_data` | Intraday |
| Floors | `get_floors` | Intraday |
| Heart rate | `get_heart_rates` | Intraday values plus resting, min, max |
| HRV | `get_hrv_data` | Nightly summary and readings |
| Sleep | `get_sleep_data` | Largest daily payload (about 125 kB): stages, movement, respiration, heart rate, stress and body battery during sleep |
| Stress | `get_stress_data` | Intraday. `get_all_day_stress` returns the same payload; collect one. |
| Respiration | `get_respiration_data` | Intraday |
| SpO2 | `get_spo2_data` | |
| Intensity minutes | `get_intensity_minutes_data` | |
| Hydration, lifestyle logging, weigh-ins | `get_hydration_data`, `get_lifestyle_logging_data`, `get_daily_weigh_ins` | Mostly user-entered |
| Daily events | `get_all_day_events` | |

### Training and performance

| Family | Call |
|---|---|
| Training readiness | `get_training_readiness`, `get_morning_training_readiness` |
| Training status and load | `get_training_status`, `get_daily_training_status`, `get_training_four_week_load_balance` |
| VO2 max and fitness age | `get_max_metrics_range`, `get_fitnessage_data` |
| Predictions and thresholds | `get_race_predictions`, `get_lactate_threshold`, `get_cycling_ftp` |
| Scores | `get_endurance_score`, `get_hill_score` |
| Zones and records | `get_heart_rate_zones`, `get_power_zones`, `get_personal_record` |
| Plans and workouts | `get_training_plans`, `get_scheduled_workouts`, `get_workouts` |

### Range calls (one call for many days)

`get_daily_steps`, `get_calories_daily`, `get_rhr_daily`, `get_sleep_daily`,
`get_hrv_data_range`, `get_body_battery`, `get_max_metrics_range`,
`get_body_composition`, `get_weigh_ins`, `get_blood_pressure`,
`get_weekly_steps`, `get_weekly_stress`, `get_weekly_intensity_minutes`,
`get_training_load_activities`, `get_activities_by_date`.

These make the daily-summary part of a backfill cheap. Intraday detail still
needs one call per day and family.

### Activities

| Call | Notes |
|---|---|
| `get_activities_by_date`, `get_activities` | List with summary fields |
| `get_activity` | Summary of one activity |
| `get_activity_details` | Time series and GPS track; about 900 kB for one activity |
| `get_activity_splits`, `get_activity_typed_splits`, `get_activity_split_summaries` | Laps and splits |
| `get_activity_hr_in_timezones`, `get_activity_power_in_timezones` | Time in zones |
| `get_activity_weather`, `get_activity_exercise_sets`, `get_activity_gear` | |

### Empty for this account

`get_body_battery_events`, `get_max_metrics` (the range variant has data),
`get_goals`, `get_running_tolerance`, `get_activity_gear`. Empty responses are
normal and must be stored as "no data", not treated as errors.

## Implications for the collector

- **Volume**: roughly 250 kB of raw JSON per day of wellness data, and up to
  1 MB per activity with full details. A year for one user is in the order of
  100 to 300 MB raw, so activity details are worth compressing or fetching lazily.
- **Backfill**: use range calls first so charts fill quickly, then walk back day
  by day for intraday detail at a polite pace.
- **Duplicates**: skip `get_all_day_stress` and prefer `get_stats_and_body` or
  `get_user_summary`, not both.
- **Device dependence**: which families have data depends on the watch; every
  family must tolerate being empty.
- **Typing**: the library has no type information; our interface wraps it and
  mypy needs an exception for the import.

## Fixtures

The raw samples from the spike stay local (`.garmin-tokens/samples/`, git-ignored)
because they contain personal data. Fixtures are added per metric family in
phase 3, through a scrubbing step that replaces identifiers, names, device
serials and GPS coordinates before anything is committed.
