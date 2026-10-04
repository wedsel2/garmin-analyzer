"""Samples within a day as series in buckets of time, and what happened then. See ADR 18."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from garmin_analyzer.metrics import Series
from garmin_analyzer.models import (
    Activity,
    BodyBatterySample,
    HeartRateSample,
    HrvReading,
    RespirationSample,
    SleepSession,
    StepInterval,
    StressSample,
)


@dataclass(frozen=True)
class IntradayMetric:
    label: str
    unit: str
    at: InstrumentedAttribute[datetime]
    value: InstrumentedAttribute[Any]
    # Steps add up within a bucket; the others are averaged.
    total: bool = False


INTRADAY_METRICS: dict[str, IntradayMetric] = {
    "heart_rate": IntradayMetric(
        "Heart rate", "bpm", HeartRateSample.measured_at, HeartRateSample.bpm
    ),
    "stress": IntradayMetric("Stress", "", StressSample.measured_at, StressSample.level),
    "body_battery": IntradayMetric(
        "Body battery", "", BodyBatterySample.measured_at, BodyBatterySample.level
    ),
    "steps": IntradayMetric("Steps", "", StepInterval.start_at, StepInterval.steps, total=True),
    "respiration": IntradayMetric(
        "Respiration",
        "breaths/min",
        RespirationSample.measured_at,
        RespirationSample.breaths_per_min,
    ),
    "hrv": IntradayMetric("HRV during sleep", "ms", HrvReading.measured_at, HrvReading.hrv_ms),
}


def intraday_series(
    db: Session,
    user_id: uuid.UUID,
    start: datetime,
    bucket_seconds: int,
    buckets: int,
    keys: list[str],
) -> Series:
    """Per metric a value for each bucket of time from start, None where there are no samples."""
    end = start + timedelta(seconds=bucket_seconds * buckets)
    series: Series = {key: [None] * buckets for key in keys}
    for key in series:
        metric = INTRADAY_METRICS[key]
        table = metric.at.class_.__table__
        # Grouped by its label: the same expression written twice would get
        # two parameters, which PostgreSQL does not see as the same.
        bucket = func.floor(func.extract("epoch", metric.at - start) / bucket_seconds).label(
            "bucket"
        )
        value = func.sum(metric.value) if metric.total else func.avg(metric.value)
        rows = db.execute(
            select(bucket, value)
            .where(table.c.user_id == user_id, metric.at >= start, metric.at < end)
            .group_by("bucket")
        )
        for index, amount in rows:
            series[key][int(index)] = round(float(amount), 1)
    return series


@dataclass(frozen=True)
class Event:
    """A sleep or an activity: something with a beginning and an end."""

    start_at: datetime
    end_at: datetime
    label: str


def sleeps_between(db: Session, user_id: uuid.UUID, start: datetime, end: datetime) -> list[Event]:
    """The sleeps that overlap the time from start to end."""
    sleeps = db.scalars(
        select(SleepSession)
        .where(
            SleepSession.user_id == user_id,
            SleepSession.start_at < end,
            SleepSession.end_at > start,
        )
        .order_by(SleepSession.start_at)
    )
    return [Event(sleep.start_at, sleep.end_at, "Sleep") for sleep in sleeps]


# No activity is taken to last longer; bounds the search for ones that began earlier.
LONGEST_ACTIVITY = timedelta(days=2)


def activities_between(
    db: Session, user_id: uuid.UUID, start: datetime, end: datetime
) -> list[Event]:
    """The activities that overlap the time from start to end, by the name the user gave them."""
    activities = db.scalars(
        select(Activity)
        .where(
            Activity.user_id == user_id,
            Activity.start_at < end,
            Activity.start_at > start - LONGEST_ACTIVITY,
            # The legs of a multi-sport activity are activities of their own.
            Activity.is_parent.is_(False),
        )
        .order_by(Activity.start_at)
    )
    events = []
    for activity in activities:
        seconds = activity.elapsed_duration_s or activity.duration_s or 0
        end_at = activity.start_at + timedelta(seconds=seconds)
        if end_at > start:
            label = (
                activity.name or (activity.type_key or "activity").replace("_", " ").capitalize()
            )
            events.append(Event(activity.start_at, end_at, label))
    return events
