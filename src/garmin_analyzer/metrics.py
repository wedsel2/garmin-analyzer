"""Daily metrics as series: what the charts and the JSON API read. See ADR 18.

A daily metric is a number column of a table that has a calendar_date, so one
value per user and day.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Table, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from garmin_analyzer.models import (
    DailySummary,
    HrvSummary,
    SleepSession,
    TrainingReadiness,
    TrainingStatus,
)


@dataclass(frozen=True)
class DailyMetric:
    label: str
    unit: str
    column: InstrumentedAttribute[Any]
    # None when neither direction is better in itself, as for training load.
    higher_is_better: bool | None = None
    # What the stored number is multiplied by to get the unit.
    scale: float = 1


HOURS = 1 / 3600

DAILY_METRICS: dict[str, DailyMetric] = {
    "sleep_score": DailyMetric("Sleep score", "", SleepSession.score, True),
    "hrv": DailyMetric("HRV last night", "ms", HrvSummary.last_night_avg, True),
    "resting_hr": DailyMetric("Resting heart rate", "bpm", DailySummary.resting_hr, False),
    "body_battery_high": DailyMetric("Body battery high", "", DailySummary.body_battery_high, True),
    "training_readiness": DailyMetric("Training readiness", "", TrainingReadiness.score, True),
    "avg_stress": DailyMetric("Stress", "", DailySummary.avg_stress, False),
    "steps": DailyMetric("Steps", "", DailySummary.steps, True),
    "acute_load": DailyMetric("Acute load", "", TrainingStatus.acute_load),
    # The range in which Garmin calls the HRV of this user balanced.
    "hrv_baseline_low": DailyMetric("Baseline low", "ms", HrvSummary.baseline_balanced_low),
    "hrv_baseline_high": DailyMetric("Baseline high", "ms", HrvSummary.baseline_balanced_upper),
    "body_battery_low": DailyMetric("Body battery low", "", DailySummary.body_battery_low, True),
    "sleep_duration": DailyMetric("Sleep", "h", SleepSession.sleep_s, True, HOURS),
    "sleep_deep": DailyMetric("Deep", "h", SleepSession.deep_s, True, HOURS),
    "sleep_light": DailyMetric("Light", "h", SleepSession.light_s, scale=HOURS),
    "sleep_rem": DailyMetric("REM", "h", SleepSession.rem_s, True, HOURS),
    "sleep_awake": DailyMetric("Awake", "h", SleepSession.awake_s, False, HOURS),
}

Series = dict[str, list[float | None]]


def daily_series(
    db: Session, user_id: uuid.UUID, start: date, end: date, keys: list[str]
) -> Series:
    """The values of each metric for every day from start to end, None where there is none."""
    days = (end - start).days + 1
    series: Series = {key: [None] * days for key in keys}
    by_table: dict[Table, list[str]] = {}
    for key in series:
        by_table.setdefault(DAILY_METRICS[key].column.class_.__table__, []).append(key)
    for table, table_keys in by_table.items():
        rows = db.execute(
            select(table.c.calendar_date, *(DAILY_METRICS[key].column for key in table_keys))
            .where(table.c.user_id == user_id, table.c.calendar_date.between(start, end))
            # A table with several rows a day, such as training readiness, gives
            # them in order of time: the last one that has a value counts.
            .order_by(*table.primary_key.columns)
        )
        for day, *values in rows:
            for key, value in zip(table_keys, values, strict=True):
                if value is not None:
                    scale = DAILY_METRICS[key].scale
                    series[key][(day - start).days] = (
                        value if scale == 1 else round(value * scale, 2)
                    )
    return series


def mean(values: list[float | None], at_least: int = 1) -> float | None:
    """The average of the values that are there, when there are at least so many."""
    measured = [value for value in values if value is not None]
    if len(measured) < at_least:
        return None
    return round(sum(measured) / len(measured), 2)


def rolling_series(
    db: Session, user_id: uuid.UUID, start: date, end: date, keys: list[str], window: int
) -> Series:
    """Per day the average of the window of days that ends on it.

    Reads the days before start that the first windows need. A window in which
    fewer than half of the days have a value gives None.
    """
    daily = daily_series(db, user_id, start - timedelta(days=window - 1), end, keys)
    days = (end - start).days + 1
    return {
        key: [mean(values[offset : offset + window], window // 2 + 1) for offset in range(days)]
        for key, values in daily.items()
    }


def weekly_series(
    db: Session, user_id: uuid.UUID, start: date, end: date, keys: list[str]
) -> tuple[list[date], Series]:
    """The average per week, Monday to Sunday, with the Monday of each week.

    The first week is the one that start falls in; the last one stops at end.
    """
    monday = start - timedelta(days=start.weekday())
    daily = daily_series(db, user_id, monday, end, keys)
    weeks = range(0, (end - monday).days + 1, 7)
    return (
        [monday + timedelta(days=offset) for offset in weeks],
        {
            key: [mean(values[offset : offset + 7]) for offset in weeks]
            for key, values in daily.items()
        },
    )


def first_day(db: Session, user_id: uuid.UUID) -> date | None:
    """The earliest day there is a daily summary or a sleep for."""
    days = [
        db.scalar(select(func.min(model.calendar_date)).where(model.user_id == user_id))
        for model in (DailySummary, SleepSession)
    ]
    return min((day for day in days if day is not None), default=None)
