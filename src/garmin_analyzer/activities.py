"""Reading activities for the pages: the list, one activity, and its samples.

The samples of an activity are not in a table: they are read from the stored
details response when someone looks at the activity. See ADR 12.
"""

import uuid
from dataclasses import dataclass
from math import ceil
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from garmin_analyzer.models import Activity, ActivityLap, ActivityZone, RawPayload

PAGE_SIZE = 25
# The largest number an activity can have in the database.
MAX_ACTIVITY_ID = 2**63 - 1
# At most this many values per series and points of the route go to the browser.
MAX_SAMPLES = 600
MAX_ROUTE_POINTS = 1000

# Sports in which people think in time per kilometre instead of kilometres per hour.
PACE_SPORTS = ("running", "walking", "hiking")

# A series -> the names Garmin gives the metric, the first one present is used.
SAMPLE_KEYS = {
    "heart_rate": ("directHeartRate",),
    "speed": ("directSpeed",),
    "elevation": ("directElevation",),
    "power": ("directPower",),
    "cadence": ("directDoubleCadence", "directRunCadence", "directBikeCadence"),
}
TIME_KEYS = ("sumElapsedDuration", "sumDuration")
MPS_TO_KMH = 3.6


def uses_pace(type_key: str | None) -> bool:
    return any(sport in (type_key or "") for sport in PACE_SPORTS)


def whole_activities(user_id: uuid.UUID) -> Any:
    """The condition for the activities of a user that are shown as one.

    A multi-sport activity is left out: its legs are activities of their own.
    """
    return (Activity.user_id == user_id) & Activity.is_parent.is_(False)


def sports(db: Session, user_id: uuid.UUID) -> list[str]:
    """The sports the user has activities of."""
    keys = db.scalars(
        select(Activity.type_key)
        .where(whole_activities(user_id), Activity.type_key.is_not(None))
        .distinct()
        .order_by(Activity.type_key)
    )
    return [key for key in keys if key]


def activity_page(
    db: Session, user_id: uuid.UUID, sport: str | None, page: int
) -> tuple[list[Activity], int]:
    """A page of activities, newest first, and how many pages there are."""
    conditions = [whole_activities(user_id)]
    if sport:
        conditions.append(Activity.type_key == sport)
    total = db.scalar(select(func.count()).select_from(Activity).where(*conditions)) or 0
    activities = db.scalars(
        select(Activity)
        .where(*conditions)
        .order_by(Activity.start_at.desc())
        .limit(PAGE_SIZE)
        .offset((page - 1) * PAGE_SIZE)
    )
    return list(activities), max(1, ceil(total / PAGE_SIZE))


def laps_of(db: Session, user_id: uuid.UUID, activity_id: int) -> list[ActivityLap]:
    return list(
        db.scalars(
            select(ActivityLap)
            .where(ActivityLap.user_id == user_id, ActivityLap.activity_id == activity_id)
            .order_by(ActivityLap.lap_index)
        )
    )


@dataclass(frozen=True)
class ZoneTime:
    number: int
    low_boundary: int | None
    seconds: float
    # Of the time in all zones, 0 to 100.
    share: int


def zones_of(db: Session, user_id: uuid.UUID, activity_id: int, kind: str) -> list[ZoneTime]:
    """Time in each heart rate or power zone, empty when none was spent in any."""
    zones = list(
        db.scalars(
            select(ActivityZone)
            .where(
                ActivityZone.user_id == user_id,
                ActivityZone.activity_id == activity_id,
                ActivityZone.kind == kind,
            )
            .order_by(ActivityZone.zone_number)
        )
    )
    total = sum(zone.seconds or 0 for zone in zones)
    if not total:
        return []
    return [
        ZoneTime(
            zone.zone_number,
            zone.low_boundary,
            zone.seconds or 0,
            round(100 * (zone.seconds or 0) / total),
        )
        for zone in zones
    ]


def details_of(db: Session, user_id: uuid.UUID, activity_id: int) -> Any | None:
    """The stored details response of an activity of this user."""
    return db.scalar(
        select(RawPayload.payload).where(
            RawPayload.user_id == user_id,
            RawPayload.endpoint == "activity_details",
            RawPayload.resource_key == str(activity_id),
        )
    )


def has_details(db: Session, user_id: uuid.UUID, activity_id: int) -> bool:
    return (
        db.scalar(
            select(RawPayload.id).where(
                RawPayload.user_id == user_id,
                RawPayload.endpoint == "activity_details",
                RawPayload.resource_key == str(activity_id),
            )
        )
        is not None
    )


@dataclass(frozen=True)
class Samples:
    # Seconds since the start for each value of the series.
    seconds: list[float]
    # heart_rate (bpm), speed (km/h), elevation (m), power (W), cadence (per minute).
    series: dict[str, list[float | None]]
    # Longitude and latitude.
    route: list[tuple[float, float]]


def measured(key: str, value: Any) -> float | None:
    """A sample as a number, None when it is missing or one of Garmin's negative markers."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    # Only height can really be below zero.
    if value < 0 and key != "elevation":
        return None
    return value * MPS_TO_KMH if key == "speed" else float(value)


def thinned(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    step = ceil(len(points) / MAX_ROUTE_POINTS)
    return points[::step] if step > 1 else points


def route_of(payload: dict[str, Any], rows: list[list[Any]], index: dict[str, int]) -> list[Any]:
    """The positions of an activity as (longitude, latitude), from the samples or the polyline."""
    if "directLatitude" in index and "directLongitude" in index:
        pairs = [
            (row[index["directLongitude"]], row[index["directLatitude"]])
            for row in rows
            if len(row) > max(index["directLongitude"], index["directLatitude"])
        ]
    else:
        polyline = (payload.get("geoPolylineDTO") or {}).get("polyline") or []
        pairs = [(point.get("lon"), point.get("lat")) for point in polyline]
    return [
        (float(lon), float(lat))
        for lon, lat in pairs
        if isinstance(lon, int | float) and isinstance(lat, int | float) and (lon or lat)
    ]


def samples_from(payload: Any) -> Samples | None:
    """The series and the route in a details response, thinned out for a chart."""
    if not isinstance(payload, dict):
        return None
    index = {
        descriptor["key"]: descriptor["metricsIndex"]
        for descriptor in payload.get("metricDescriptors") or []
        if isinstance(descriptor, dict)
        and isinstance(descriptor.get("key"), str)
        and isinstance(descriptor.get("metricsIndex"), int)
    }
    rows = [
        row["metrics"]
        for row in payload.get("activityDetailMetrics") or []
        if isinstance(row, dict) and isinstance(row.get("metrics"), list)
    ]
    if not rows:
        return None

    def column(names: tuple[str, ...]) -> int | None:
        return next((index[name] for name in names if name in index), None)

    def value(row: list[Any], at: int | None) -> Any:
        return row[at] if at is not None and at < len(row) else None

    columns = {key: column(names) for key, names in SAMPLE_KEYS.items()}
    time_column = column(TIME_KEYS)
    size = ceil(len(rows) / MAX_SAMPLES)
    seconds: list[float] = []
    series: dict[str, list[float | None]] = {key: [] for key in columns}
    for first in range(0, len(rows), size):
        bucket = rows[first : first + size]
        moment = measured("time", value(bucket[0], time_column))
        seconds.append(moment if moment is not None else float(first))
        for key, at in columns.items():
            values = [
                number for row in bucket if (number := measured(key, value(row, at))) is not None
            ]
            series[key].append(round(sum(values) / len(values), 1) if values else None)
    return Samples(
        seconds,
        {key: values for key, values in series.items() if any(v is not None for v in values)},
        thinned(route_of(payload, rows, index)),
    )
