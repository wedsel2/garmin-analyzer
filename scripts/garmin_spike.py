# /// script
# requires-python = ">=3.14"
# dependencies = ["garminconnect==0.3.17"]
# ///
"""Phase 2 spike: confirm Garmin login and see which metrics exist.

Run locally against your own account, never in CI:

    uv run scripts/garmin_spike.py

You sign in to Garmin in your own browser and paste the resulting address. The
script never performs a scripted sign-in: Garmin blocks those and bans the IP.

Everything is written to .garmin-tokens/ (git-ignored):
  tokens/       Garmin tokens; a second run should log in without a password
  samples/      raw responses, containing personal health data
  report.json   shapes only (keys and value types, no values), safe to share
"""

import base64
import json
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

OUT = Path(".garmin-tokens")
TOKENS = OUT / "tokens"
SAMPLES = OUT / "samples"
SSO_EMBED = "https://sso.garmin.com/sso/embed"
SIGNIN_PARAMS = {
    "id": "gauth-widget",
    "embedWidget": "true",
    "gauthHost": SSO_EMBED,
    "service": SSO_EMBED,
    "source": SSO_EMBED,
    "redirectAfterAccountLoginUrl": SSO_EMBED,
    "redirectAfterAccountCreationUrl": SSO_EMBED,
}
PAUSE_SECONDS = 1.0
MAX_DEPTH = 6


def shape(value: Any, depth: int = 0) -> Any:
    """Describe a response by its keys and value types, without any values."""
    if isinstance(value, dict):
        if depth >= MAX_DEPTH:
            return f"dict({len(value)})"
        return {str(key): shape(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        if not value:
            return "list(0)"
        return {"list": len(value), "item": shape(value[0], depth + 1)}
    return type(value).__name__


def token_lifetime(token: str | None) -> dict[str, Any] | None:
    """Read the issue and expiry times from a JWT without verifying it."""
    if not token or token.count(".") != 2:
        return None
    payload = token.split(".")[1]
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except ValueError:
        return None
    if "exp" not in claims:
        return None
    lifetime: dict[str, Any] = {
        "expires": datetime.fromtimestamp(claims["exp"], UTC).isoformat(),
    }
    if "iat" in claims:
        lifetime["valid_for_hours"] = round((claims["exp"] - claims["iat"]) / 3600, 1)
    return lifetime


def browser_login() -> Garmin:
    """Let a person sign in in their own browser; we only receive the ticket.

    Garmin blocks scripted sign-ins, so the script never touches the sign-in
    page. It exchanges the single-use ticket from the final URL for tokens.
    """
    print("1. Open this address in your browser and sign in to Garmin:\n")
    print(f"   {SSO_EMBED.replace('/embed', '/signin')}?{urlencode(SIGNIN_PARAMS)}\n")
    print("2. When the page is blank or says Success, copy the full address from")
    print("   the address bar (it contains ticket=ST-...) and paste it here quickly;")
    print("   the ticket expires within a minute or so.\n")
    pasted = input("Address or ticket: ")
    match = re.search(r"ST-[A-Za-z0-9-]+", pasted)
    if not match:
        raise SystemExit(
            "No ticket found. If the address bar has none, open the page source "
            "(Ctrl+U), search for 'ticket=ST-' and paste that value."
        )
    garmin = Garmin()
    # Private in the library: the same call its own widget login ends with.
    garmin.client._exchange_service_ticket(match.group(0), service_url=SSO_EMBED)
    garmin.client.dump(str(TOKENS))

    garmin = Garmin()
    garmin.login(str(TOKENS))
    print("Ticket exchanged; tokens stored and verified.")
    return garmin


def log_in() -> tuple[Garmin, dict[str, Any]]:
    """Log in, preferring stored tokens, and report how it went."""
    facts: dict[str, Any] = {}
    if TOKENS.exists():
        try:
            garmin = Garmin()
            garmin.login(str(TOKENS))
        except Exception as error:
            print(f"Stored tokens did not work ({type(error).__name__}), logging in again.")
            facts["stored_tokens_error"] = type(error).__name__
        else:
            print("Logged in from stored tokens, no password needed.")
            facts["method"] = "stored tokens"
            return garmin, facts

    garmin = browser_login()
    facts["method"] = "browser ticket"
    return garmin, facts


def endpoints(garmin: Garmin, day: str, week_ago: str) -> dict[str, Callable[[], Any]]:
    """Read-only calls only. Nothing here changes data in Garmin Connect."""
    month = date.fromisoformat(day)
    calls: dict[str, Callable[[], Any]] = {
        # profile and devices
        "user_profile": garmin.get_user_profile,
        "userprofile_settings": garmin.get_userprofile_settings,
        "devices": garmin.get_devices,
        "device_last_used": garmin.get_device_last_used,
        "primary_training_device": garmin.get_primary_training_device,
        # daily wellness
        "user_summary": lambda: garmin.get_user_summary(day),
        "stats_and_body": lambda: garmin.get_stats_and_body(day),
        "steps_data": lambda: garmin.get_steps_data(day),
        "floors": lambda: garmin.get_floors(day),
        "heart_rates": lambda: garmin.get_heart_rates(day),
        "rhr_day": lambda: garmin.get_rhr_day(day),
        "hrv_data": lambda: garmin.get_hrv_data(day),
        "sleep_data": lambda: garmin.get_sleep_data(day),
        "stress_data": lambda: garmin.get_stress_data(day),
        "all_day_stress": lambda: garmin.get_all_day_stress(day),
        "all_day_events": lambda: garmin.get_all_day_events(day),
        "body_battery_events": lambda: garmin.get_body_battery_events(day),
        "respiration_data": lambda: garmin.get_respiration_data(day),
        "spo2_data": lambda: garmin.get_spo2_data(day),
        "intensity_minutes_data": lambda: garmin.get_intensity_minutes_data(day),
        "hydration_data": lambda: garmin.get_hydration_data(day),
        "lifestyle_logging_data": lambda: garmin.get_lifestyle_logging_data(day),
        "daily_weigh_ins": lambda: garmin.get_daily_weigh_ins(day),
        # training and performance
        "training_readiness": lambda: garmin.get_training_readiness(day),
        "morning_training_readiness": lambda: garmin.get_morning_training_readiness(day),
        "training_status": lambda: garmin.get_training_status(day),
        "daily_training_status": lambda: garmin.get_daily_training_status(day),
        "training_four_week_load_balance": lambda: garmin.get_training_four_week_load_balance(day),
        "max_metrics": lambda: garmin.get_max_metrics(day),
        "fitnessage_data": lambda: garmin.get_fitnessage_data(day),
        "race_predictions": garmin.get_race_predictions,
        "lactate_threshold": garmin.get_lactate_threshold,
        "cycling_ftp": garmin.get_cycling_ftp,
        "heart_rate_zones": garmin.get_heart_rate_zones,
        "power_zones": garmin.get_power_zones,
        "personal_record": garmin.get_personal_record,
        "goals": garmin.get_goals,
        "training_plans": garmin.get_training_plans,
        "scheduled_workouts": lambda: garmin.get_scheduled_workouts(month.year, month.month),
        "workouts": lambda: garmin.get_workouts(0, 5),
        # ranges, which would make backfilling much cheaper than day-by-day calls
        "range_daily_steps": lambda: garmin.get_daily_steps(week_ago, day),
        "range_calories_daily": lambda: garmin.get_calories_daily(week_ago, day),
        "range_rhr_daily": lambda: garmin.get_rhr_daily(week_ago, day),
        "range_sleep_daily": lambda: garmin.get_sleep_daily(week_ago, day),
        "range_hrv_data": lambda: garmin.get_hrv_data_range(week_ago, day),
        "range_body_battery": lambda: garmin.get_body_battery(week_ago, day),
        "range_max_metrics": lambda: garmin.get_max_metrics_range(week_ago, day),
        "range_body_composition": lambda: garmin.get_body_composition(week_ago, day),
        "range_weigh_ins": lambda: garmin.get_weigh_ins(week_ago, day),
        "range_blood_pressure": lambda: garmin.get_blood_pressure(week_ago, day),
        "range_endurance_score": lambda: garmin.get_endurance_score(week_ago, day),
        "range_hill_score": lambda: garmin.get_hill_score(week_ago, day),
        "range_running_tolerance": lambda: garmin.get_running_tolerance(week_ago, day),
        "range_weekly_intensity_minutes": lambda: garmin.get_weekly_intensity_minutes(
            week_ago, day
        ),
        "range_weekly_steps": lambda: garmin.get_weekly_steps(day, 4),
        "range_weekly_stress": lambda: garmin.get_weekly_stress(day, 4),
        "range_training_load_activities": lambda: garmin.get_training_load_activities(
            week_ago, day
        ),
        # activities
        "activity_count": garmin.count_activities,
        "activities": lambda: garmin.get_activities(0, 5),
        "range_activities_by_date": lambda: garmin.get_activities_by_date(week_ago, day),
    }
    return calls


def activity_endpoints(garmin: Garmin, activity_id: str) -> dict[str, Callable[[], Any]]:
    return {
        "activity": lambda: garmin.get_activity(activity_id),
        "activity_details": lambda: garmin.get_activity_details(activity_id),
        "activity_splits": lambda: garmin.get_activity_splits(activity_id),
        "activity_typed_splits": lambda: garmin.get_activity_typed_splits(activity_id),
        "activity_split_summaries": lambda: garmin.get_activity_split_summaries(activity_id),
        "activity_hr_in_timezones": lambda: garmin.get_activity_hr_in_timezones(activity_id),
        "activity_power_in_timezones": lambda: garmin.get_activity_power_in_timezones(activity_id),
        "activity_weather": lambda: garmin.get_activity_weather(activity_id),
        "activity_exercise_sets": lambda: garmin.get_activity_exercise_sets(activity_id),
        "activity_gear": lambda: garmin.get_activity_gear(activity_id),
    }


def probe(calls: dict[str, Callable[[], Any]]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name, call in calls.items():
        started = time.monotonic()
        try:
            data = call()
        except Exception as error:
            results[name] = {"status": "error", "error": type(error).__name__}
            print(f"  error  {name}: {type(error).__name__}")
        else:
            text = json.dumps(data, default=str)
            (SAMPLES / f"{name}.json").write_text(text, encoding="utf-8")
            results[name] = {
                "status": "ok" if data else "empty",
                "seconds": round(time.monotonic() - started, 2),
                "bytes": len(text),
                "shape": shape(data),
            }
            print(f"  {results[name]['status']:<6} {name} ({len(text)} bytes)")
        time.sleep(PAUSE_SECONDS)
    return results


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    try:
        garmin, login_facts = log_in()
    except GarminConnectAuthenticationError as error:
        raise SystemExit(f"Garmin rejected the credentials or MFA code: {error}") from None
    except (GarminConnectTooManyRequestsError, GarminConnectConnectionError) as error:
        raise SystemExit(
            f"Login blocked or failed: {error}\n"
            "Do not retry straight away: repeated attempts extend the block. "
            "Check that you can sign in at https://connect.garmin.com, then wait an hour."
        ) from None

    day = (date.today() - timedelta(days=1)).isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    print(f"Probing endpoints for {day} and the range {week_ago}..{day}")
    results = probe(endpoints(garmin, day, week_ago))

    last_activity = garmin.get_last_activity()
    if last_activity:
        print("Probing the most recent activity")
        results |= probe(activity_endpoints(garmin, str(last_activity["activityId"])))

    report = {
        "library_version": version("garminconnect"),
        "generated": datetime.now(UTC).isoformat(),
        "login": login_facts,
        "token_fields": sorted(json.loads(garmin.client.dumps())),
        "access_token": token_lifetime(garmin.client.di_token),
        "refresh_token": token_lifetime(garmin.client.di_refresh_token),
        "endpoints": results,
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    counts = {
        status: sum(1 for result in results.values() if result["status"] == status)
        for status in ("ok", "empty", "error")
    }
    print(f"Done: {counts}. Report written to {OUT / 'report.json'}")


if __name__ == "__main__":
    main()
