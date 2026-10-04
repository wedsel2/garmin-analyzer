"""The goals page and the forms to add, change and remove a goal. See ADR 20."""

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from garmin_analyzer import goals
from garmin_analyzer.goals import GoalError
from garmin_analyzer.models import GoalEvent, User, WeeklyGoal
from garmin_analyzer.web.activity_pages import tempo
from garmin_analyzer.web.shared import (
    CurrentUser,
    Db,
    duration,
    redirect,
    sentence,
    templates,
    today,
)

router = APIRouter()

# The events to come that the overview has room for.
EVENTS_ON_OVERVIEW = 3


def long_date(day: date) -> str:
    return f"{day.day} {day:%b %Y}"


def goals_context(
    db: Session, user: User, day: date, events: int = goals.MAX_GOALS
) -> dict[str, Any]:
    """What a page needs to show the weekly goals and the events to come."""
    return {
        "progress": goals.weekly_progress(db, user.id, day),
        "upcoming": goals.upcoming_events(db, user.id, day, events),
        "weeks_back": goals.WEEKS_BACK,
        "tempo": tempo,
        "long_date": long_date,
    }


def overview_context(db: Session, user: User, day: date) -> dict[str, Any]:
    return goals_context(db, user, day, EVENTS_ON_OVERVIEW)


@router.get("/goals")
def goals_page(request: Request, db: Db, user: CurrentUser) -> Response:
    day = today()
    return templates.TemplateResponse(
        request,
        "goals.html",
        {
            "user": user,
            "past": goals.past_events(db, user.id, day),
            **goals_context(db, user, day),
        },
    )


def event_form(
    request: Request,
    user: User,
    values: dict[str, str],
    event: GoalEvent | None = None,
    error: str | None = None,
) -> Response:
    """The form of an event: a new one, or one to change. Comes back with what was entered."""
    return templates.TemplateResponse(
        request,
        "goal_event.html",
        {
            "user": user,
            "event": event,
            "values": values,
            "error": error,
            "sports": goals.SPORTS,
            "max_name_length": goals.MAX_NAME_LENGTH,
        },
        status_code=400 if error else 200,
    )


def event_values(event: GoalEvent) -> dict[str, str]:
    return {
        "name": event.name,
        "day": event.event_date.isoformat(),
        "sport": event.sport or "",
        "distance": "" if event.distance_m is None else f"{event.distance_m / 1000:g}",
        "target_time": duration(event.target_time_s),
    }


def own_event(db: Session, user: User, event_id: uuid.UUID) -> GoalEvent:
    """The event when it is one of the user; that of someone else does not exist."""
    event = goals.find_event(db, user.id, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="No such goal")
    return event


def save_event(
    request: Request, db: Session, user: User, event: GoalEvent | None, values: dict[str, str]
) -> Response:
    """Store what the form holds, in a new event when there is none yet. Commits."""
    target = event or GoalEvent(user_id=user.id)
    try:
        if event is None:
            goals.check_room(db, user.id, GoalEvent)
        goals.set_event(
            target,
            values["name"],
            values["day"],
            values["sport"],
            values["distance"],
            values["target_time"],
        )
    except GoalError as error:
        return event_form(request, user, values, event, sentence(error))
    db.add(target)
    db.commit()
    return redirect("/goals")


# Before the routes with an id in the same place.
@router.get("/goals/events/new")
def new_event_form(request: Request, user: CurrentUser) -> Response:
    return event_form(request, user, {})


@router.post("/goals/events/new")
def new_event(
    request: Request,
    db: Db,
    user: CurrentUser,
    name: Annotated[str, Form()] = "",
    day: Annotated[str, Form()] = "",
    sport: Annotated[str, Form()] = "",
    distance: Annotated[str, Form()] = "",
    target_time: Annotated[str, Form()] = "",
) -> Response:
    values = {
        "name": name,
        "day": day,
        "sport": sport,
        "distance": distance,
        "target_time": target_time,
    }
    return save_event(request, db, user, None, values)


@router.get("/goals/events/{event_id}")
def change_event_form(request: Request, db: Db, user: CurrentUser, event_id: uuid.UUID) -> Response:
    event = own_event(db, user, event_id)
    return event_form(request, user, event_values(event), event)


@router.post("/goals/events/{event_id}")
def change_event(
    request: Request,
    db: Db,
    user: CurrentUser,
    event_id: uuid.UUID,
    name: Annotated[str, Form()] = "",
    day: Annotated[str, Form()] = "",
    sport: Annotated[str, Form()] = "",
    distance: Annotated[str, Form()] = "",
    target_time: Annotated[str, Form()] = "",
) -> Response:
    values = {
        "name": name,
        "day": day,
        "sport": sport,
        "distance": distance,
        "target_time": target_time,
    }
    return save_event(request, db, user, own_event(db, user, event_id), values)


@router.post("/goals/events/{event_id}/remove")
def remove_event(db: Db, user: CurrentUser, event_id: uuid.UUID) -> Response:
    db.delete(own_event(db, user, event_id))
    db.commit()
    return redirect("/goals")


def weekly_form(
    request: Request,
    user: User,
    values: dict[str, str],
    goal: WeeklyGoal | None = None,
    error: str | None = None,
) -> Response:
    """The form of a weekly goal: a new one, or one to change."""
    return templates.TemplateResponse(
        request,
        "goal_weekly.html",
        {
            "user": user,
            "goal": goal,
            "values": values,
            "error": error,
            "sports": goals.SPORTS,
            "measures": {measure.value: info for measure, info in goals.MEASURES.items()},
        },
        status_code=400 if error else 200,
    )


def own_weekly_goal(db: Session, user: User, goal_id: uuid.UUID) -> WeeklyGoal:
    goal = goals.find_weekly_goal(db, user.id, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="No such goal")
    return goal


def save_weekly_goal(
    request: Request, db: Session, user: User, goal: WeeklyGoal | None, values: dict[str, str]
) -> Response:
    """Store what the form holds, in a new goal when there is none yet. Commits."""
    target = goal or WeeklyGoal(user_id=user.id)
    try:
        if goal is None:
            goals.check_room(db, user.id, WeeklyGoal)
        goals.set_weekly_goal(target, values["measure"], values["target"], values["sport"])
    except GoalError as error:
        return weekly_form(request, user, values, goal, sentence(error))
    db.add(target)
    db.commit()
    return redirect("/goals")


@router.get("/goals/weekly/new")
def new_weekly_form(request: Request, user: CurrentUser) -> Response:
    return weekly_form(request, user, {})


@router.post("/goals/weekly/new")
def new_weekly_goal(
    request: Request,
    db: Db,
    user: CurrentUser,
    measure: Annotated[str, Form()] = "",
    target: Annotated[str, Form()] = "",
    sport: Annotated[str, Form()] = "",
) -> Response:
    values = {"measure": measure, "target": target, "sport": sport}
    return save_weekly_goal(request, db, user, None, values)


@router.get("/goals/weekly/{goal_id}")
def change_weekly_form(request: Request, db: Db, user: CurrentUser, goal_id: uuid.UUID) -> Response:
    goal = own_weekly_goal(db, user, goal_id)
    values = {
        "measure": goal.measure.value,
        "target": f"{goal.target:g}",
        "sport": goal.sport or "",
    }
    return weekly_form(request, user, values, goal)


@router.post("/goals/weekly/{goal_id}")
def change_weekly_goal(
    request: Request,
    db: Db,
    user: CurrentUser,
    goal_id: uuid.UUID,
    measure: Annotated[str, Form()] = "",
    target: Annotated[str, Form()] = "",
    sport: Annotated[str, Form()] = "",
) -> Response:
    values = {"measure": measure, "target": target, "sport": sport}
    return save_weekly_goal(request, db, user, own_weekly_goal(db, user, goal_id), values)


@router.post("/goals/weekly/{goal_id}/remove")
def remove_weekly_goal(db: Db, user: CurrentUser, goal_id: uuid.UUID) -> Response:
    db.delete(own_weekly_goal(db, user, goal_id))
    db.commit()
    return redirect("/goals")
