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

from garmin_analyzer.models import (
    Base,
    BodyBatterySample,
    DailySummary,
    HeartRateSample,
    HrvReading,
    HrvSummary,
    RespirationSample,
    SleepSession,
    StepInterval,
    StressSample,
)

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


def from_gmt_text(value: str) -> datetime:
    """Parse the zone-less GMT form Garmin uses, such as 2026-01-14T23:00:00.0."""
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def series(
    payload: Any, values_key: str, descriptors_key: str, column: str
) -> list[tuple[int, Any]]:
    """Read (timestamp, value) pairs from a Garmin values array.

    Garmin sends arrays of positional values plus a descriptor list naming each
    position. Positions are looked up by name, so a reordering on the Garmin
    side does not silently shift our data.
    """
    if not isinstance(payload, dict):
        return []
    positions: dict[str, int] = {}
    for descriptor in payload.get(descriptors_key) or []:
        names = [v for v in descriptor.values() if isinstance(v, str)]
        indexes = [v for v in descriptor.values() if isinstance(v, int)]
        if names and indexes:
            positions[names[0]] = indexes[0]
    if "timestamp" not in positions or column not in positions:
        return []
    return [
        (entry[positions["timestamp"]], entry[positions[column]])
        for entry in payload.get(values_key) or []
    ]


def measured(value: Any) -> bool:
    """Garmin marks unmeasured points with null or negative numbers such as -1 and -2."""
    return value is not None and value >= 0


def stress_rows(payload: Any) -> list[Row]:
    pairs = series(payload, "stressValuesArray", "stressValueDescriptorsDTOList", "stressLevel")
    return [
        {"measured_at": from_epoch_ms(timestamp), "level": level}
        for timestamp, level in pairs
        if measured(level)
    ]


def body_battery_rows(payload: Any) -> list[Row]:
    pairs = series(
        payload,
        "bodyBatteryValuesArray",
        "bodyBatteryValueDescriptorsDTOList",
        "bodyBatteryLevel",
    )
    return [
        {"measured_at": from_epoch_ms(timestamp), "level": level}
        for timestamp, level in pairs
        if measured(level)
    ]


def respiration_rows(payload: Any) -> list[Row]:
    pairs = series(
        payload,
        "respirationValuesArray",
        "respirationValueDescriptorsDTOList",
        "respiration",
    )
    return [
        {"measured_at": from_epoch_ms(timestamp), "breaths_per_min": value}
        for timestamp, value in pairs
        if measured(value)
    ]


def hrv_summary_rows(payload: Any) -> list[Row]:
    summary = payload.get("hrvSummary") if isinstance(payload, dict) else None
    if not summary or not summary.get("calendarDate"):
        return []
    baseline = summary.get("baseline") or {}
    return [
        {
            "calendar_date": date.fromisoformat(summary["calendarDate"]),
            "weekly_avg": summary.get("weeklyAvg"),
            "last_night_avg": summary.get("lastNightAvg"),
            "last_night_5min_high": summary.get("lastNight5MinHigh"),
            "baseline_low_upper": baseline.get("lowUpper"),
            "baseline_balanced_low": baseline.get("balancedLow"),
            "baseline_balanced_upper": baseline.get("balancedUpper"),
            "status": summary.get("status"),
        }
    ]


def hrv_reading_rows(payload: Any) -> list[Row]:
    readings = payload.get("hrvReadings") if isinstance(payload, dict) else None
    return [
        {"measured_at": from_gmt_text(reading["readingTimeGMT"]), "hrv_ms": reading["hrvValue"]}
        for reading in readings or []
        if measured(reading.get("hrvValue"))
    ]


def step_interval_rows(payload: Any) -> list[Row]:
    if not isinstance(payload, list):
        return []
    return [
        {
            "start_at": from_gmt_text(interval["startGMT"]),
            "end_at": from_gmt_text(interval["endGMT"]),
            "steps": interval["steps"],
        }
        for interval in payload
        if measured(interval.get("steps"))
    ]


Parser = Callable[[Any], list[Row]]

# Endpoint name -> the tables it feeds. Endpoints without an entry stay raw only.
NORMALISERS: dict[str, list[tuple[type[Base], Parser]]] = {
    "user_summary": [(DailySummary, daily_summary_rows)],
    "sleep_data": [(SleepSession, sleep_session_rows)],
    "heart_rates": [(HeartRateSample, heart_rate_rows)],
    "stress_data": [(StressSample, stress_rows), (BodyBatterySample, body_battery_rows)],
    "respiration_data": [(RespirationSample, respiration_rows)],
    "hrv_data": [(HrvSummary, hrv_summary_rows), (HrvReading, hrv_reading_rows)],
    "steps_data": [(StepInterval, step_interval_rows)],
}


def normalise(session: Session, user_id: uuid.UUID, endpoint: str, payload: Any) -> int:
    """Upsert the rows derived from one raw payload. Returns the number of rows."""
    total = 0
    for model, parse in NORMALISERS.get(endpoint, []):
        rows = [row | {"user_id": user_id} for row in parse(payload)]
        if not rows:
            continue
        keys = sorted(column.name for column in model.__table__.primary_key)
        statement = insert(model).values(rows)
        updates = {name: statement.excluded[name] for name in rows[0] if name not in keys}
        session.execute(statement.on_conflict_do_update(index_elements=keys, set_=updates))
        total += len(rows)
    return total
