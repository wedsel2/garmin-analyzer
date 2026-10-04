"""Daily metrics as series: what the charts and the JSON API read. See ADR 18.

A daily metric is a number column of a table that has a calendar_date, so one
value per user and day.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Table, select
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


DAILY_METRICS: dict[str, DailyMetric] = {
    "sleep_score": DailyMetric("Sleep score", "", SleepSession.score, True),
    "hrv": DailyMetric("HRV last night", "ms", HrvSummary.last_night_avg, True),
    "resting_hr": DailyMetric("Resting heart rate", "bpm", DailySummary.resting_hr, False),
    "body_battery_high": DailyMetric("Body battery high", "", DailySummary.body_battery_high, True),
    "training_readiness": DailyMetric("Training readiness", "", TrainingReadiness.score, True),
    "avg_stress": DailyMetric("Stress", "", DailySummary.avg_stress, False),
    "steps": DailyMetric("Steps", "", DailySummary.steps, True),
    "acute_load": DailyMetric("Acute load", "", TrainingStatus.acute_load),
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
                    series[key][(day - start).days] = value
    return series
