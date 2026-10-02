"""Turn raw Garmin responses into rows of the normalised tables.

Parsers are pure functions from a payload to column values, so they can be
re-run over stored raw payloads when a parser changes. Garmin omits fields or
sends null depending on the device, so every measurement is optional.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from garmin_analyzer.models import Base, DailySummary, HeartRateSample, SleepSession

Row = dict[str, Any]

DAILY_SUMMARY_FIELDS = {
    "steps": "totalSteps",
    "step_goal": "dailyStepGoal",
    "distance_m": "totalDistanceMeters",
    "floors_ascended": "floorsAscended",
    "floors_descended": "floorsDescended",
    "total_kcal": "totalKilocalories",
    "active_kcal": "activeKilocalories",
    "bmr_kcal": "bmrKilocalories",
    "highly_active_s": "highlyActiveSeconds",
    "active_s": "activeSeconds",
    "sedentary_s": "sedentarySeconds",
    "moderate_intensity_min": "moderateIntensityMinutes",
    "vigorous_intensity_min": "vigorousIntensityMinutes",
    "resting_hr": "restingHeartRate",
    "min_hr": "minHeartRate",
    "max_hr": "maxHeartRate",
    "avg_stress": "averageStressLevel",
    "max_stress": "maxStressLevel",
    "body_battery_high": "bodyBatteryHighestValue",
    "body_battery_low": "bodyBatteryLowestValue",
    "body_battery_charged": "bodyBatteryChargedValue",
    "body_battery_drained": "bodyBatteryDrainedValue",
    "avg_spo2": "averageSpo2",
    "lowest_spo2": "lowestSpo2",
    "avg_waking_respiration": "avgWakingRespirationValue",
}

SLEEP_FIELDS = {
    "sleep_s": "sleepTimeSeconds",
    "nap_s": "napTimeSeconds",
    "deep_s": "deepSleepSeconds",
    "light_s": "lightSleepSeconds",
    "rem_s": "remSleepSeconds",
    "awake_s": "awakeSleepSeconds",
    "awake_count": "awakeCount",
    "avg_respiration": "averageRespirationValue",
    "avg_stress": "avgSleepStress",
}


def from_epoch_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, UTC)


def daily_summary_rows(payload: Any) -> list[Row]:
    if not isinstance(payload, dict) or not payload.get("calendarDate"):
        return []
    row: Row = {column: payload.get(field) for column, field in DAILY_SUMMARY_FIELDS.items()}
    row["calendar_date"] = date.fromisoformat(payload["calendarDate"])
    return [row]


def sleep_session_rows(payload: Any) -> list[Row]:
    daily = payload.get("dailySleepDTO") if isinstance(payload, dict) else None
    # A night without recorded sleep still returns the wrapper, without times.
    if not daily or not daily.get("sleepStartTimestampGMT") or not daily.get("calendarDate"):
        return []
    row: Row = {column: daily.get(field) for column, field in SLEEP_FIELDS.items()}
    overall = (daily.get("sleepScores") or {}).get("overall") or {}
    row |= {
        "calendar_date": date.fromisoformat(daily["calendarDate"]),
        "start_at": from_epoch_ms(daily["sleepStartTimestampGMT"]),
        "end_at": from_epoch_ms(daily["sleepEndTimestampGMT"]),
        "score": overall.get("value"),
        "score_qualifier": overall.get("qualifierKey"),
        "avg_hrv": payload.get("avgOvernightHrv"),
        "hrv_status": payload.get("hrvStatus"),
        "resting_hr": payload.get("restingHeartRate"),
        "body_battery_change": payload.get("bodyBatteryChange"),
    }
    return [row]


def heart_rate_rows(payload: Any) -> list[Row]:
    values = payload.get("heartRateValues") if isinstance(payload, dict) else None
    # Gaps in the recording arrive as [timestamp, null].
    return [
        {"measured_at": from_epoch_ms(timestamp), "bpm": bpm}
        for timestamp, bpm in values or []
        if bpm is not None
    ]


# Endpoint name -> (table, parser). Endpoints without an entry stay raw only.
NORMALISERS: dict[str, tuple[type[Base], Callable[[Any], list[Row]]]] = {
    "user_summary": (DailySummary, daily_summary_rows),
    "sleep_data": (SleepSession, sleep_session_rows),
    "heart_rates": (HeartRateSample, heart_rate_rows),
}


def normalise(session: Session, user_id: uuid.UUID, endpoint: str, payload: Any) -> int:
    """Upsert the rows derived from one raw payload. Returns the number of rows."""
    if endpoint not in NORMALISERS:
        return 0
    model, parse = NORMALISERS[endpoint]
    rows = [row | {"user_id": user_id} for row in parse(payload)]
    if not rows:
        return 0
    keys = sorted(column.name for column in model.__table__.primary_key)
    statement = insert(model).values(rows)
    updates = {name: statement.excluded[name] for name in rows[0] if name not in keys}
    session.execute(statement.on_conflict_do_update(index_elements=keys, set_=updates))
    return len(rows)
