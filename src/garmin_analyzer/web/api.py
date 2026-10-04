"""The JSON API that the charts read. See ADR 18.

Every answer holds only data of the signed-in user.
"""

from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from garmin_analyzer.metrics import DAILY_METRICS, daily_series, rolling_series, weekly_series
from garmin_analyzer.models import SleepSession
from garmin_analyzer.web.shared import ApiUser, Db

router = APIRouter(prefix="/api/v1", tags=["series"])

# Ten years: more than a watch has recorded, and still a small answer.
MAX_DAYS = 3660
MAX_ROLLING_DAYS = 90

Start = Annotated[date, Query(description="First day, as YYYY-MM-DD.")]
End = Annotated[date, Query(description="Last day, included.")]
Metrics = Annotated[
    str, Query(description="Metric names separated by commas: " + ", ".join(DAILY_METRICS))
]


class DailySeries(BaseModel):
    """One value per day for each metric asked for, in the order of `dates`."""

    dates: list[date]
    series: dict[str, list[float | None]]
    # Only when asked for: per day the average of the days up to and including it.
    rolling: dict[str, list[float | None]] | None = None


class WeeklySeries(BaseModel):
    """The average per week, Monday to Sunday. `dates` holds the Monday of each week."""

    dates: list[date]
    series: dict[str, list[float | None]]


class Nights(BaseModel):
    """When the sleep that ended on each day began and ended, null for a day without one."""

    dates: list[date]
    start_at: list[datetime | None]
    end_at: list[datetime | None]


def days_between(start: date, end: date) -> list[date]:
    if not 0 <= (end - start).days < MAX_DAYS:
        raise HTTPException(422, f"end must be on or after start, at most {MAX_DAYS} days apart")
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def known(metrics: str) -> list[str]:
    """The metric names in a request, refused when one is not in the registry."""
    keys = list(dict.fromkeys(key.strip() for key in metrics.split(",") if key.strip()))
    unknown = [key for key in keys if key not in DAILY_METRICS]
    if unknown or not keys:
        raise HTTPException(422, f"unknown metrics: {', '.join(unknown) or '(none given)'}")
    return keys


@router.get("/daily", response_model_exclude_none=True)
def daily(
    db: Db,
    user: ApiUser,
    start: Start,
    end: End,
    metrics: Metrics,
    rolling: Annotated[
        int | None,
        Query(ge=2, le=MAX_ROLLING_DAYS, description="Also give the average over this many days."),
    ] = None,
) -> DailySeries:
    """Daily values of the signed-in user. A day without a value is null."""
    keys = known(metrics)
    return DailySeries(
        dates=days_between(start, end),
        series=daily_series(db, user.id, start, end, keys),
        rolling=rolling_series(db, user.id, start, end, keys, rolling) if rolling else None,
    )


@router.get("/weekly")
def weekly(db: Db, user: ApiUser, start: Start, end: End, metrics: Metrics) -> WeeklySeries:
    """Weekly averages of the signed-in user, from the week that `start` falls in."""
    keys = known(metrics)
    days_between(start, end)
    mondays, series = weekly_series(db, user.id, start, end, keys)
    return WeeklySeries(dates=mondays, series=series)


@router.get("/nights")
def nights(db: Db, user: ApiUser, start: Start, end: End) -> Nights:
    """Bed and wake times of the signed-in user, as moments in UTC."""
    dates = days_between(start, end)
    sleeps = {
        sleep.calendar_date: sleep
        for sleep in db.scalars(
            select(SleepSession).where(
                SleepSession.user_id == user.id, SleepSession.calendar_date.between(start, end)
            )
        )
    }
    return Nights(
        dates=dates,
        start_at=[sleeps[day].start_at if day in sleeps else None for day in dates],
        end_at=[sleeps[day].end_at if day in sleeps else None for day in dates],
    )
