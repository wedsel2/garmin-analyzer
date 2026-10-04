"""What the training page shows beyond daily metrics: activity time, race times, readiness."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_analyzer.metrics import Series, daily_series
from garmin_analyzer.models import Activity, TrainingReadiness

# The sports with the most time get a colour of their own; the rest is "Other".
SPORTS_SHOWN = 3
OTHER = "Other"


def sport_label(type_key: str | None) -> str:
    return (type_key or "activity").replace("_", " ").capitalize()


def activity_times(
    db: Session, user_id: uuid.UUID, start: date, end: date
) -> list[tuple[date, str, float]]:
    """The day (in UTC), the sport and the hours of every activity that began from start to end."""
    rows = db.execute(
        select(Activity.start_at, Activity.type_key, Activity.duration_s).where(
            Activity.user_id == user_id,
            Activity.start_at >= datetime.combine(start, time.min, UTC),
            Activity.start_at < datetime.combine(end + timedelta(days=1), time.min, UTC),
            # The legs of a multi-sport activity are activities of their own.
            Activity.is_parent.is_(False),
            Activity.duration_s.is_not(None),
        )
    )
    return [
        (begun.astimezone(UTC).date(), sport_label(kind), (seconds or 0) / 3600)
        for begun, kind, seconds in rows
    ]


def weekly_hours(
    db: Session, user_id: uuid.UUID, start: date, end: date
) -> tuple[list[date], Series]:
    """Hours of activities per week and sport, with the Monday of each week.

    The first week is the one that start falls in. Sports beyond the few with
    the most time are added up as "Other".
    """
    monday = start - timedelta(days=start.weekday())
    mondays = [monday + timedelta(days=offset) for offset in range(0, (end - monday).days + 1, 7)]
    activities = activity_times(db, user_id, monday, end)
    totals: dict[str, float] = {}
    for _, sport, hours in activities:
        totals[sport] = totals.get(sport, 0) + hours
    shown = sorted(totals, key=lambda sport: -totals[sport])[:SPORTS_SHOWN]
    names = [*shown, OTHER] if len(totals) > len(shown) else shown
    sums = {name: [0.0] * len(mondays) for name in names}
    for day, sport, hours in activities:
        sums[sport if sport in shown else OTHER][(day - monday).days // 7] += hours
    return mondays, {name: [round(hours, 2) for hours in weeks] for name, weeks in sums.items()}


def daily_minutes(db: Session, user_id: uuid.UUID, start: date, end: date) -> list[float | None]:
    """Minutes of activities for every day from start to end, None for a day without any."""
    minutes: list[float | None] = [None] * ((end - start).days + 1)
    for day, _, hours in activity_times(db, user_id, start, end):
        index = (day - start).days
        minutes[index] = round((minutes[index] or 0) + hours * 60)
    return minutes


RACES = {
    "race_5k": "5 km",
    "race_10k": "10 km",
    "race_half_marathon": "Half marathon",
    "race_marathon": "Marathon",
}


@dataclass(frozen=True)
class Prediction:
    distance: str
    seconds: float
    # Against the first prediction in the period; negative is faster.
    change: float


def predictions(db: Session, user_id: uuid.UUID, start: date, end: date) -> list[Prediction]:
    """The latest predicted race times in the period and how they changed within it."""
    result = []
    for key, values in daily_series(db, user_id, start, end, list(RACES)).items():
        known = [value for value in values if value is not None]
        if known:
            result.append(Prediction(RACES[key], known[-1], known[-1] - known[0]))
    return result


FACTORS = {
    "sleep_factor_pct": "Sleep last night",
    "sleep_history_factor_pct": "Sleep in recent days",
    "recovery_time_factor_pct": "Recovery time",
    "acwr_factor_pct": "Training load",
    "hrv_factor_pct": "HRV",
    "stress_history_factor_pct": "Stress in recent days",
}


@dataclass(frozen=True)
class Readiness:
    day: date
    score: int | None
    level: str | None
    # How much each factor helps, 0 to 100.
    factors: list[tuple[str, int]]


def latest_readiness(db: Session, user_id: uuid.UUID) -> Readiness | None:
    """The most recent training readiness and what it is made of."""
    reading = db.scalar(
        select(TrainingReadiness)
        .where(TrainingReadiness.user_id == user_id)
        .order_by(TrainingReadiness.measured_at.desc())
        .limit(1)
    )
    if reading is None:
        return None
    factors = [
        (label, value)
        for column, label in FACTORS.items()
        if (value := getattr(reading, column)) is not None
    ]
    return Readiness(reading.calendar_date, reading.score, reading.level, factors)
