"""The list of activities and the page of one activity."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import Response

from garmin_analyzer import activities
from garmin_analyzer.models import Activity, ActivityLap, User
from garmin_analyzer.web.overview import phrase
from garmin_analyzer.web.shared import (
    CurrentUser,
    Db,
    duration,
    kilometres,
    number,
    templates,
)

router = APIRouter()

# The charts of an activity, in the order shown: series, title and unit.
SAMPLE_CHARTS = (
    ("heart_rate", "Heart rate", "bpm"),
    ("speed", "Speed", "km/h"),
    ("elevation", "Elevation", "m"),
    ("power", "Power", "W"),
    ("cadence", "Cadence", "per minute"),
)


def tempo(type_key: str | None, metres_per_second: float | None) -> str:
    """A speed the way the sport talks about it: time per kilometre, or kilometres per hour."""
    if not metres_per_second:
        return ""
    if activities.uses_pace(type_key):
        return f"{duration(1000 / metres_per_second)} /km"
    return f"{metres_per_second * 3.6:.1f} km/h"


def figures_of(activity: Activity) -> list[tuple[str, str]]:
    """What was measured over the whole activity, as a label and a text each."""
    pace = activities.uses_pace(activity.type_key)

    def whole(value: float | None, unit: str) -> str:
        return "" if value is None else f"{number(value)} {unit}".strip()

    def effect(value: float | None) -> str:
        return "" if value is None else f"{value:.1f}"

    figures = [
        ("Distance", kilometres(activity.distance_m) if activity.distance_m else ""),
        ("Time", duration(activity.duration_s)),
        ("Moving time", duration(activity.moving_duration_s)),
        (
            "Average pace" if pace else "Average speed",
            tempo(activity.type_key, activity.avg_speed_mps),
        ),
        ("Average heart rate", whole(activity.avg_hr, "bpm")),
        ("Highest heart rate", whole(activity.max_hr, "bpm")),
        ("Elevation gain", whole(activity.elevation_gain_m, "m")),
        ("Average power", whole(activity.avg_power, "W")),
        ("Normalised power", whole(activity.norm_power, "W")),
        ("Average cadence", whole(activity.avg_cadence, "per minute")),
        ("Calories", whole(activity.calories, "kcal")),
        ("Training load", whole(activity.training_load, "")),
        ("Aerobic effect", effect(activity.aerobic_training_effect)),
        ("Anaerobic effect", effect(activity.anaerobic_training_effect)),
        ("Effect", phrase(activity.training_effect_label or "")),
    ]
    return [(label, text) for label, text in figures if text]


def lap_rows(type_key: str | None, laps: list[ActivityLap]) -> list[dict[str, str]]:
    return [
        {
            "number": str(lap.lap_index + 1),
            "distance": kilometres(lap.distance_m) if lap.distance_m else "",
            "time": duration(lap.duration_s),
            "tempo": tempo(type_key, lap.avg_speed_mps),
            "heart_rate": "" if lap.avg_hr is None else f"{number(lap.avg_hr)} bpm",
            "power": "" if lap.avg_power is None else f"{number(lap.avg_power)} W",
        }
        for lap in laps
    ]


@router.get("/activities")
def activity_list(
    request: Request,
    db: Db,
    user: CurrentUser,
    sport: str = "",
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
) -> Response:
    sports = activities.sports(db, user.id)
    sport = sport if sport in sports else ""
    shown, pages = activities.activity_page(db, user.id, sport or None, page)
    return templates.TemplateResponse(
        request,
        "activities.html",
        {
            "user": user,
            "activities": shown,
            "sports": sports,
            "sport": sport,
            "page": page,
            "pages": pages,
            "phrase": phrase,
            "tempo": tempo,
        },
    )


ActivityId = Annotated[int, Path(ge=1, le=activities.MAX_ACTIVITY_ID)]


def own_activity(db: Db, user: User, activity_id: int) -> Activity:
    """The activity, when it is one of this user: otherwise it does not exist for them."""
    activity = db.get(Activity, (user.id, activity_id))
    if activity is None:
        raise HTTPException(404, "No such activity")
    return activity


@router.get("/activities/{activity_id}")
def activity_detail(
    request: Request, db: Db, user: CurrentUser, activity_id: ActivityId
) -> Response:
    activity = own_activity(db, user, activity_id)
    laps = activities.laps_of(db, user.id, activity_id)
    return templates.TemplateResponse(
        request,
        "activity.html",
        {
            "user": user,
            "activity": activity,
            "sport": phrase(activity.type_key or "activity"),
            "figures": figures_of(activity),
            "laps": lap_rows(activity.type_key, laps),
            "paced": activities.uses_pace(activity.type_key),
            "zones": {
                "Heart rate": ("bpm", activities.zones_of(db, user.id, activity_id, "hr")),
                "Power": ("W", activities.zones_of(db, user.id, activity_id, "power")),
            },
            "samples_src": (
                f"/api/v1/activities/{activity_id}/samples"
                if activities.has_details(db, user.id, activity_id)
                else None
            ),
            "charts": SAMPLE_CHARTS,
        },
    )
