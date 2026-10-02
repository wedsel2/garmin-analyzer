"""Parsers for training and performance metrics. See normalise.py for the registry."""

from datetime import UTC, date, datetime
from typing import Any

Row = dict[str, Any]

READINESS_FIELDS = {
    "score": "score",
    "level": "level",
    "feedback": "feedbackShort",
    "sleep_score": "sleepScore",
    "recovery_time_min": "recoveryTime",
    "acute_load": "acuteLoad",
    "hrv_weekly_avg": "hrvWeeklyAverage",
    "sleep_factor_pct": "sleepScoreFactorPercent",
    "recovery_time_factor_pct": "recoveryTimeFactorPercent",
    "acwr_factor_pct": "acwrFactorPercent",
    "stress_history_factor_pct": "stressHistoryFactorPercent",
    "hrv_factor_pct": "hrvFactorPercent",
    "sleep_history_factor_pct": "sleepHistoryFactorPercent",
}

RACE_FIELDS = {
    "time_5k_s": "time5K",
    "time_10k_s": "time10K",
    "time_half_marathon_s": "timeHalfMarathon",
    "time_marathon_s": "timeMarathon",
}


def as_list(payload: Any) -> list[Any]:
    """Garmin returns one object for a single day and a list for a range."""
    if isinstance(payload, list):
        return payload
    return [payload] if isinstance(payload, dict) else []


def day_of(value: str) -> date:
    """The date part of a date or date-time string."""
    return date.fromisoformat(value[:10])


def primary_device_entry(by_device: Any) -> dict[str, Any] | None:
    """Pick the entry of the primary training device from a map keyed by device id."""
    entries = [e for e in (by_device or {}).values() if isinstance(e, dict)]
    primary = [e for e in entries if e.get("primaryTrainingDevice")]
    candidates = primary or entries
    return candidates[0] if candidates else None


def training_readiness_rows(payload: Any) -> list[Row]:
    rows = []
    for entry in as_list(payload):
        if not entry.get("timestamp") or not entry.get("calendarDate"):
            continue
        row: Row = {column: entry.get(field) for column, field in READINESS_FIELDS.items()}
        row["measured_at"] = datetime.fromisoformat(entry["timestamp"]).replace(tzinfo=UTC)
        row["calendar_date"] = day_of(entry["calendarDate"])
        rows.append(row)
    return rows


def training_status_rows(payload: Any) -> list[Row]:
    if not isinstance(payload, dict):
        return []
    recent = payload.get("mostRecentTrainingStatus") or {}
    status = primary_device_entry(recent.get("latestTrainingStatusData"))
    if not status or not status.get("calendarDate"):
        return []
    balance = (
        primary_device_entry(
            (payload.get("mostRecentTrainingLoadBalance") or {}).get(
                "metricsTrainingLoadBalanceDTOMap"
            )
        )
        or {}
    )
    load = status.get("acuteTrainingLoadDTO") or {}
    return [
        {
            "calendar_date": day_of(status["calendarDate"]),
            "status_code": status.get("trainingStatus"),
            "status": status.get("trainingStatusFeedbackPhrase"),
            "sport": status.get("sport"),
            "fitness_trend": status.get("fitnessTrend"),
            "acute_load": load.get("dailyTrainingLoadAcute"),
            "chronic_load": load.get("dailyTrainingLoadChronic"),
            "acwr": load.get("dailyAcuteChronicWorkloadRatio"),
            "acwr_status": load.get("acwrStatus"),
            "load_aerobic_low": balance.get("monthlyLoadAerobicLow"),
            "load_aerobic_high": balance.get("monthlyLoadAerobicHigh"),
            "load_anaerobic": balance.get("monthlyLoadAnaerobic"),
            "load_balance": balance.get("trainingBalanceFeedbackPhrase"),
        }
    ]


def vo2max_rows(payload: Any) -> list[Row]:
    rows = []
    for entry in as_list(payload):
        running = entry.get("generic") or {}
        cycling = entry.get("cycling") or {}
        acclimation = entry.get("heatAltitudeAcclimation") or {}
        day = running.get("calendarDate") or cycling.get("calendarDate")
        if not day:
            continue
        rows.append(
            {
                "calendar_date": day_of(day),
                "running": running.get("vo2MaxPreciseValue"),
                "cycling": cycling.get("vo2MaxPreciseValue"),
                "heat_acclimation_pct": acclimation.get("heatAcclimationPercentage"),
                "altitude_acclimation": acclimation.get("altitudeAcclimation"),
            }
        )
    return rows


def vo2max_from_training_status_rows(payload: Any) -> list[Row]:
    """The training status response carries the latest VO2 max in the same shape."""
    return vo2max_rows(payload.get("mostRecentVO2Max") if isinstance(payload, dict) else None)


def race_prediction_rows(payload: Any) -> list[Row]:
    return [
        {column: entry.get(field) for column, field in RACE_FIELDS.items()}
        | {"calendar_date": day_of(entry["calendarDate"])}
        for entry in as_list(payload)
        if entry.get("calendarDate")
    ]


def fitness_age_rows(payload: Any) -> list[Row]:
    if not isinstance(payload, dict) or not payload.get("lastUpdated"):
        return []
    return [
        {
            "calendar_date": day_of(payload["lastUpdated"]),
            "fitness_age": payload.get("fitnessAge"),
            "chronological_age": payload.get("chronologicalAge"),
            "achievable_fitness_age": payload.get("achievableFitnessAge"),
        }
    ]


def power_threshold_rows(payload: Any) -> list[Row]:
    """Functional threshold power, from the cycling FTP or the lactate threshold response."""
    entries = as_list(payload)
    if isinstance(payload, dict) and "power" in payload:
        entries = as_list(payload["power"])
    required = ("sport", "calendarDate", "functionalThresholdPower")
    return [
        {
            "sport": entry["sport"],
            "calendar_date": day_of(entry["calendarDate"]),
            "ftp_watts": entry["functionalThresholdPower"],
            "power_to_weight": entry.get("powerToWeight"),
        }
        for entry in entries
        if all(entry.get(field) for field in required)
    ]
