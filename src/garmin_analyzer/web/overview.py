"""What the overview shows: the latest value of the main metrics against the weeks before."""

import re
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute, Session

from garmin_analyzer.metrics import DAILY_METRICS, DailyMetric, daily_series
from garmin_analyzer.models import (
    Activity,
    HrvSummary,
    SleepSession,
    TrainingReadiness,
    TrainingStatus,
)

# The days before today that a value is compared with and the trend line shows.
PERIOD_DAYS = 28
# Fewer other days than this make no average worth comparing with.
MIN_DAYS_FOR_AVERAGE = 3
RECENT_ACTIVITIES = 5

# The tiles in the order shown, each with the column that holds Garmin's word for the value.
TILES: dict[str, InstrumentedAttribute[Any] | None] = {
    "sleep_score": SleepSession.score_qualifier,
    "hrv": HrvSummary.status,
    "resting_hr": None,
    "body_battery_high": None,
    "training_readiness": TrainingReadiness.level,
    "avg_stress": None,
    "steps": None,
    "acute_load": TrainingStatus.status,
}


def phrase(code: str) -> str:
    """One of Garmin's codes, such as PRODUCTIVE_2 or multi_sport, as words."""
    return re.sub(r"_\d+$", "", code).replace("_", " ").capitalize()


@dataclass(frozen=True)
class Tile:
    key: str
    metric: DailyMetric
    # The most recent value in the period and the day it is of.
    value: float | None = None
    day: date | None = None
    # Of the other days in the period.
    average: float | None = None
    note: str | None = None

    @property
    def delta(self) -> int | None:
        if self.value is None or self.average is None:
            return None
        return round(self.value - self.average)

    @property
    def verdict(self) -> str | None:
        """Whether the value is "better" or "worse" than the average, when that can be said."""
        better_when_higher = self.metric.higher_is_better
        if not self.delta or better_when_higher is None:
            return None
        return "better" if (self.delta > 0) == better_when_higher else "worse"


def day_label(day: date, today: date) -> str:
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return f"{day.day} {day:%b}"


def period(today: date) -> tuple[date, date]:
    return today - timedelta(days=PERIOD_DAYS), today


def series_url(today: date) -> str:
    """Where the charts of the tiles get their values."""
    start, end = period(today)
    return f"/api/v1/daily?start={start}&end={end}&metrics={','.join(TILES)}"


def tiles(db: Session, user_id: uuid.UUID, today: date) -> list[Tile]:
    start, end = period(today)
    series = daily_series(db, user_id, start, end, list(TILES))
    result = []
    for key, note_column in TILES.items():
        measured = [
            (offset, value) for offset, value in enumerate(series[key]) if value is not None
        ]
        if not measured:
            result.append(Tile(key, DAILY_METRICS[key]))
            continue
        offset, value = measured[-1]
        day = start + timedelta(days=offset)
        others = [other for _, other in measured[:-1]]
        note = None
        if note_column is not None:
            table = note_column.class_.__table__
            note = db.scalar(
                select(note_column)
                .where(table.c.user_id == user_id, table.c.calendar_date == day)
                .order_by(*(column.desc() for column in table.primary_key.columns))
                .limit(1)
            )
        result.append(
            Tile(
                key,
                DAILY_METRICS[key],
                value,
                day,
                sum(others) / len(others) if len(others) >= MIN_DAYS_FOR_AVERAGE else None,
                phrase(note) if note else None,
            )
        )
    return result


def recent_activities(db: Session, user_id: uuid.UUID) -> list[Activity]:
    return list(
        db.scalars(
            select(Activity)
            .where(Activity.user_id == user_id)
            .order_by(Activity.start_at.desc())
            .limit(RECENT_ACTIVITIES)
        )
    )
