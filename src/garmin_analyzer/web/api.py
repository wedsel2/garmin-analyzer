"""The JSON API that the charts read. See ADR 18.

Every answer holds only data of the signed-in user.
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from garmin_analyzer.metrics import DAILY_METRICS, daily_series
from garmin_analyzer.web.shared import ApiUser, Db

router = APIRouter(prefix="/api/v1", tags=["series"])

# Ten years: more than a watch has recorded, and still a small answer.
MAX_DAYS = 3660


class DailySeries(BaseModel):
    """One value per day for each metric asked for, in the order of `dates`."""

    dates: list[date]
    series: dict[str, list[float | None]]


@router.get("/daily")
def daily(
    db: Db,
    user: ApiUser,
    start: Annotated[date, Query(description="First day, as YYYY-MM-DD.")],
    end: Annotated[date, Query(description="Last day, included.")],
    metrics: Annotated[
        str, Query(description="Metric names separated by commas: " + ", ".join(DAILY_METRICS))
    ],
) -> DailySeries:
    """Daily values of the signed-in user. A day without a value is null."""
    keys = list(dict.fromkeys(key.strip() for key in metrics.split(",") if key.strip()))
    unknown = [key for key in keys if key not in DAILY_METRICS]
    if unknown or not keys:
        raise HTTPException(422, f"unknown metrics: {', '.join(unknown) or '(none given)'}")
    if not 0 <= (end - start).days < MAX_DAYS:
        raise HTTPException(422, f"end must be on or after start, at most {MAX_DAYS} days apart")
    return DailySeries(
        dates=[start + timedelta(days=offset) for offset in range((end - start).days + 1)],
        series=daily_series(db, user.id, start, end, keys),
    )
