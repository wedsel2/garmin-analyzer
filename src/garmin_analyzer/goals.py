"""Goals of a user: events to train for, and what to do every week. See ADR 20.

Nothing about progress is stored: it is worked out from the activities and
Garmin's predicted race times when a page asks for it.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from garmin_analyzer.activities import whole_activities
from garmin_analyzer.models import Activity, GoalEvent, Measure, RacePrediction, WeeklyGoal

MAX_NAME_LENGTH = 100
MAX_NOTE_LENGTH = 2000
# Of each kind, per user.
MAX_GOALS = 50
# The weeks before this one that a weekly goal is looked back over.
WEEKS_BACK = 8
PAST_EVENTS_SHOWN = 20
FIRST_YEAR, LAST_YEAR = 2000, 2100
MAX_DISTANCE_KM = 10_000

# A sport to pick for a goal -> what Garmin's type of an activity of it contains,
# so that trail running counts as running and a virtual ride as cycling.
SPORTS: dict[str, tuple[str, ...]] = {
    "running": ("run",),
    "cycling": ("cycling", "biking", "bike", "ride"),
    "swimming": ("swim",),
    "walking": ("walking",),
    "hiking": ("hiking",),
    "strength": ("strength",),
}
# The sports in which an event has a distance and a time to aim for. An event of
# another sport, or of none of them, is described by its note.
DISTANCE_SPORTS = ("running", "walking", "cycling", "hiking", "swimming")


@dataclass(frozen=True)
class MeasureInfo:
    label: str
    unit: str
    # The most that can be asked of a week.
    most: float


MEASURES = {
    Measure.HOURS: MeasureInfo("Hours", "h", 100),
    Measure.DISTANCE: MeasureInfo("Distance", "km", MAX_DISTANCE_KM),
    Measure.ACTIVITIES: MeasureInfo("Activities", "", 100),
}

# The distances Garmin predicts a time for, in metres.
RACE_COLUMNS = {
    5_000: RacePrediction.time_5k_s,
    10_000: RacePrediction.time_10k_s,
    21_097.5: RacePrediction.time_half_marathon_s,
    42_195: RacePrediction.time_marathon_s,
}
# How far a distance may be off to count as one of those: 21.1 km is a half marathon.
RACE_TOLERANCE = 0.01

TIME = re.compile(r"(?:(\d{1,3}):)?(\d{1,2}):(\d{2})", re.ASCII)


class GoalError(Exception):
    """What was entered for a goal cannot be used."""


def parse_number(text: str, what: str, most: float) -> float:
    """A number above zero as people write it, with a point or a comma."""
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError:
        raise GoalError(f"{what} is not a number") from None
    # Not a number and infinity fail this too.
    if not 0 < value <= most:
        raise GoalError(f"{what} must be more than 0 and at most {most:g}")
    return value


def parse_time(text: str) -> int:
    """A length of time written as h:mm:ss or mm:ss, in seconds."""
    match = TIME.fullmatch(text.strip())
    if match is None:
        raise GoalError("write the target time as h:mm:ss or mm:ss")
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    if seconds > 59 or (match.group(1) is not None and minutes > 59):
        raise GoalError("write the target time as h:mm:ss or mm:ss")
    total = hours * 3600 + minutes * 60 + seconds
    if total == 0:
        raise GoalError("the target time must be more than 0")
    return total


def parse_sport(text: str) -> str | None:
    sport = text.strip()
    if not sport:
        return None
    if sport not in SPORTS:
        raise GoalError("pick a sport from the list")
    return sport


def is_sport(type_key: str | None, sport: str | None) -> bool:
    """Whether an activity of Garmin's type belongs to the sport; anything does to none."""
    if sport is None:
        return True
    kind = type_key or ""
    # Motorcycling has "cycling" in it.
    return "motor" not in kind and any(word in kind for word in SPORTS[sport])


def set_event(
    event: GoalEvent,
    name: str,
    day: str,
    sport: str,
    distance_km: str,
    target_time: str,
    note: str,
) -> None:
    """Fill an event from what its form holds. Changes nothing when a field is refused.

    A distance and a target time are kept only for a sport that has them.
    """
    name = name.strip()[:MAX_NAME_LENGTH]
    if not name:
        raise GoalError("give the event a name")
    try:
        event_date = date.fromisoformat(day.strip())
    except ValueError:
        raise GoalError("pick the date of the event") from None
    if not FIRST_YEAR <= event_date.year <= LAST_YEAR:
        raise GoalError(f"the date must be between {FIRST_YEAR} and {LAST_YEAR}")
    kind = parse_sport(sport)
    distance_m, target_time_s = None, None
    if kind in DISTANCE_SPORTS:
        if distance_km.strip():
            distance_m = parse_number(distance_km, "the distance", MAX_DISTANCE_KM) * 1000
        if target_time.strip():
            target_time_s = parse_time(target_time)
    # A browser sends the end of a line as two characters and counts it as one.
    note = note.replace("\r\n", "\n").strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise GoalError(f"the note can be at most {MAX_NOTE_LENGTH} characters")
    event.name = name
    event.event_date = event_date
    event.sport = kind
    event.distance_m = distance_m
    event.target_time_s = target_time_s
    event.note = note or None


def set_weekly_goal(goal: WeeklyGoal, measure: str, target: str, sport: str) -> None:
    """Fill a weekly goal from what its form holds. Changes nothing when a field is refused."""
    try:
        kind = Measure(measure)
    except ValueError:
        raise GoalError("pick what to count") from None
    # One decimal, as a week is added up and shown: 2.25 could not be reached at 2.2.
    amount = round(parse_number(target, "the target", MEASURES[kind].most), 1)
    if amount == 0:
        raise GoalError("the target must be at least 0.1")
    if kind is Measure.ACTIVITIES and amount != int(amount):
        raise GoalError("a number of activities is a whole number")
    of = parse_sport(sport)
    if kind is Measure.DISTANCE and of is not None and of not in DISTANCE_SPORTS:
        raise GoalError(f"{of} has no distance; count hours or activities")
    goal.measure = kind
    goal.target = amount
    goal.sport = of


def check_room(db: Session, user_id: uuid.UUID, model: type[GoalEvent] | type[WeeklyGoal]) -> None:
    """Refuse one more goal of a kind when the user has the most there can be."""
    count = db.scalar(select(func.count()).select_from(model).where(model.user_id == user_id))
    if (count or 0) >= MAX_GOALS:
        raise GoalError(f"you have {MAX_GOALS} of these, which is the most; remove one first")


def find_event(db: Session, user_id: uuid.UUID, event_id: uuid.UUID) -> GoalEvent | None:
    return db.scalar(
        select(GoalEvent).where(GoalEvent.user_id == user_id, GoalEvent.id == event_id)
    )


def find_weekly_goal(db: Session, user_id: uuid.UUID, goal_id: uuid.UUID) -> WeeklyGoal | None:
    return db.scalar(
        select(WeeklyGoal).where(WeeklyGoal.user_id == user_id, WeeklyGoal.id == goal_id)
    )


def midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, UTC)


def predicted_time(db: Session, user_id: uuid.UUID, event: GoalEvent) -> int | None:
    """Garmin's latest predicted time for the distance of a running event, if it has one."""
    if event.sport != "running" or event.distance_m is None:
        return None
    for metres, column in RACE_COLUMNS.items():
        if abs(event.distance_m - metres) <= metres * RACE_TOLERANCE:
            return db.scalar(
                select(column)
                .where(RacePrediction.user_id == user_id, column.is_not(None))
                .order_by(RacePrediction.calendar_date.desc())
                .limit(1)
            )
    return None


def result_of(db: Session, user_id: uuid.UUID, event: GoalEvent) -> Activity | None:
    """The longest activity of the sport of an event that began on its day, in UTC."""
    activities = db.scalars(
        select(Activity).where(
            whole_activities(user_id),
            Activity.start_at >= midnight(event.event_date),
            Activity.start_at < midnight(event.event_date + timedelta(days=1)),
        )
    )
    return max(
        (activity for activity in activities if is_sport(activity.type_key, event.sport)),
        key=lambda activity: (activity.distance_m or 0, activity.duration_s or 0),
        default=None,
    )


@dataclass(frozen=True)
class EventView:
    event: GoalEvent
    # Negative for an event that has been.
    days_to_go: int
    predicted_s: int | None = None
    result: Activity | None = None

    @property
    def countdown(self) -> str:
        days = self.days_to_go
        if days == 0:
            return "Today"
        if days == 1:
            return "Tomorrow"
        if days < 14:
            return f"In {days} days"
        return f"In {days // 7} weeks"

    @property
    def target_speed_mps(self) -> float | None:
        if not self.event.distance_m or not self.event.target_time_s:
            return None
        return self.event.distance_m / self.event.target_time_s

    @property
    def predicted_behind_s(self) -> int | None:
        """How much slower than the target Garmin predicts; negative is faster."""
        if self.predicted_s is None or self.event.target_time_s is None:
            return None
        return self.predicted_s - self.event.target_time_s


def upcoming_events(
    db: Session, user_id: uuid.UUID, today: date, limit: int = MAX_GOALS
) -> list[EventView]:
    """The events from today on, the soonest first, with what Garmin predicts for them."""
    events = db.scalars(
        select(GoalEvent)
        .where(GoalEvent.user_id == user_id, GoalEvent.event_date >= today)
        .order_by(GoalEvent.event_date, GoalEvent.created_at)
        .limit(limit)
    )
    return [
        EventView(
            event,
            (event.event_date - today).days,
            predicted_s=predicted_time(db, user_id, event),
        )
        for event in events
    ]


def past_events(db: Session, user_id: uuid.UUID, today: date) -> list[EventView]:
    """The latest events that have been, the last first, with the activity of that day."""
    events = db.scalars(
        select(GoalEvent)
        .where(GoalEvent.user_id == user_id, GoalEvent.event_date < today)
        .order_by(GoalEvent.event_date.desc(), GoalEvent.created_at)
        .limit(PAST_EVENTS_SHOWN)
    )
    return [
        EventView(event, (event.event_date - today).days, result=result_of(db, user_id, event))
        for event in events
    ]


def amount(measure: Measure, value: float) -> str:
    """How much of a measure, as written on a page."""
    text = f"{value:.0f}" if measure is Measure.ACTIVITIES else f"{value:.1f}"
    return f"{text} {MEASURES[measure].unit}".strip()


@dataclass(frozen=True)
class Progress:
    goal: WeeklyGoal
    # This week so far, in the unit of the measure.
    value: float
    # Whether each of the weeks before this one reached the target, the oldest first.
    weeks_met: list[bool]

    @property
    def title(self) -> str:
        sport, target = self.goal.sport, f"{self.goal.target:g}"
        if self.goal.measure is Measure.ACTIVITIES:
            noun = "activity" if self.goal.target == 1 else "activities"
            return f"{target} {sport} {noun} a week" if sport else f"{target} {noun} a week"
        unit = "hours" if self.goal.measure is Measure.HOURS else "km"
        return f"{target} {unit} of {sport} a week" if sport else f"{target} {unit} a week"

    @property
    def done(self) -> str:
        return amount(self.goal.measure, self.value)

    @property
    def met(self) -> bool:
        return self.value >= self.goal.target

    @property
    def weeks_reached(self) -> int:
        return sum(self.weeks_met)

    @property
    def share(self) -> int:
        """How much of the target is done, 0 to 100."""
        return min(100, round(100 * self.value / self.goal.target))


def weekly_progress(db: Session, user_id: uuid.UUID, today: date) -> list[Progress]:
    """Every weekly goal with this week so far and the weeks before it.

    A week runs from Monday to Sunday and an activity counts on the day it
    began in UTC, as on the training page. The weeks before are held against
    the target as it is now, also those from before the goal was made.
    """
    goals = list(
        db.scalars(
            select(WeeklyGoal).where(WeeklyGoal.user_id == user_id).order_by(WeeklyGoal.created_at)
        )
    )
    if not goals:
        return []
    monday = today - timedelta(days=today.weekday())
    first = monday - timedelta(weeks=WEEKS_BACK)
    activities = db.execute(
        select(
            Activity.start_at, Activity.type_key, Activity.duration_s, Activity.distance_m
        ).where(
            whole_activities(user_id),
            Activity.start_at >= midnight(first),
            Activity.start_at < midnight(monday + timedelta(weeks=1)),
        )
    ).all()
    result = []
    for goal in goals:
        weeks = [0.0] * (WEEKS_BACK + 1)
        for begun, type_key, seconds, metres in activities:
            if not is_sport(type_key, goal.sport):
                continue
            week = (begun.astimezone(UTC).date() - first).days // 7
            if goal.measure is Measure.HOURS:
                weeks[week] += (seconds or 0) / 3600
            elif goal.measure is Measure.DISTANCE:
                weeks[week] += (metres or 0) / 1000
            else:
                weeks[week] += 1
        # Rounded as shown, so that what reads as the target also counts as it.
        weeks = [round(week, 1) for week in weeks]
        result.append(Progress(goal, weeks[-1], [week >= goal.target for week in weeks[:-1]]))
    return result
