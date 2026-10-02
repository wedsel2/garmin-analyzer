"""Parsers for activities. See normalise.py for the registry and ADR 12 for scope."""

from datetime import UTC, datetime
from typing import Any

from garmin_analyzer.normalise_training import as_list

Row = dict[str, Any]

# Column -> field of an entry in the activity list.
ACTIVITY_FIELDS = {
    "name": "activityName",
    "duration_s": "duration",
    "moving_duration_s": "movingDuration",
    "elapsed_duration_s": "elapsedDuration",
    "distance_m": "distance",
    "elevation_gain_m": "elevationGain",
    "elevation_loss_m": "elevationLoss",
    "avg_speed_mps": "averageSpeed",
    "max_speed_mps": "maxSpeed",
    "calories": "calories",
    "avg_hr": "averageHR",
    "max_hr": "maxHR",
    "avg_power": "avgPower",
    "max_power": "maxPower",
    "norm_power": "normPower",
    "aerobic_training_effect": "aerobicTrainingEffect",
    "anaerobic_training_effect": "anaerobicTrainingEffect",
    "training_effect_label": "trainingEffectLabel",
    "training_load": "activityTrainingLoad",
    "vo2max": "vO2MaxValue",
    "steps": "steps",
    "lap_count": "lapCount",
    "moderate_intensity_min": "moderateIntensityMinutes",
    "vigorous_intensity_min": "vigorousIntensityMinutes",
    "location_name": "locationName",
    "start_latitude": "startLatitude",
    "start_longitude": "startLongitude",
}

LAP_FIELDS = {
    "distance_m": "distance",
    "duration_s": "duration",
    "moving_duration_s": "movingDuration",
    "elevation_gain_m": "elevationGain",
    "elevation_loss_m": "elevationLoss",
    "avg_speed_mps": "averageSpeed",
    "max_speed_mps": "maxSpeed",
    "calories": "calories",
    "avg_hr": "averageHR",
    "max_hr": "maxHR",
    "avg_power": "averagePower",
    "max_power": "maxPower",
    "intensity_type": "intensityType",
}

# Garmin names cadence per sport; the first one present is used.
ACTIVITY_CADENCE_FIELDS = (
    "averageRunningCadenceInStepsPerMinute",
    "averageBikingCadenceInRevPerMinute",
    "averageSwimCadenceInStrokesPerMinute",
)
LAP_CADENCE_FIELDS = ("averageRunCadence", "averageBikeCadence", "averageSwimCadence")


def from_gmt_text(value: str) -> datetime:
    """Parse a zone-less GMT time, with either a space or a T between date and time."""
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def first_present(entry: dict[str, Any], fields: tuple[str, ...]) -> Any:
    return next((entry[field] for field in fields if entry.get(field) is not None), None)


def activity_rows(payload: Any) -> list[Row]:
    rows = []
    for entry in as_list(payload):
        if not entry.get("activityId") or not entry.get("startTimeGMT"):
            continue
        row: Row = {column: entry.get(field) for column, field in ACTIVITY_FIELDS.items()}
        row |= {
            "activity_id": entry["activityId"],
            "start_at": from_gmt_text(entry["startTimeGMT"]),
            "type_key": (entry.get("activityType") or {}).get("typeKey"),
            "avg_cadence": first_present(entry, ACTIVITY_CADENCE_FIELDS),
            # A multi-sport activity is a parent whose legs are activities of their own.
            "is_parent": bool(entry.get("parent")),
        }
        rows.append(row)
    return rows


def lap_rows(payload: Any) -> list[Row]:
    if not isinstance(payload, dict) or not payload.get("activityId"):
        return []
    rows = []
    for lap in payload.get("lapDTOs") or []:
        if lap.get("lapIndex") is None or not lap.get("startTimeGMT"):
            continue
        row: Row = {column: lap.get(field) for column, field in LAP_FIELDS.items()}
        row |= {
            "activity_id": payload["activityId"],
            "lap_index": lap["lapIndex"],
            "start_at": from_gmt_text(lap["startTimeGMT"]),
            "avg_cadence": first_present(lap, LAP_CADENCE_FIELDS),
        }
        rows.append(row)
    return rows


def zone_rows(payload: Any, activity_id: str, kind: str) -> list[Row]:
    """Time in zones. The response does not name its activity, so the caller does."""
    if not activity_id.isdigit():
        return []
    return [
        {
            "activity_id": int(activity_id),
            "kind": kind,
            "zone_number": zone["zoneNumber"],
            "seconds": zone.get("secsInZone"),
            "low_boundary": zone.get("zoneLowBoundary"),
        }
        for zone in as_list(payload)
        if zone.get("zoneNumber") is not None
    ]


def hr_zone_rows(payload: Any, activity_id: str) -> list[Row]:
    return zone_rows(payload, activity_id, "hr")


def power_zone_rows(payload: Any, activity_id: str) -> list[Row]:
    return zone_rows(payload, activity_id, "power")
