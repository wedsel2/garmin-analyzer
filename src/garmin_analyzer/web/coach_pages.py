"""The coach page: agreeing to it, asking for a report and reading reports. See ADR 21."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import delete
from sqlalchemy.orm import Session

from garmin_analyzer import coach
from garmin_analyzer.coach import CoachError
from garmin_analyzer.metrics import first_day
from garmin_analyzer.models import CoachReport, ReportStatus, User
from garmin_analyzer.web.shared import CurrentUser, Db, redirect, sentence, templates, today

router = APIRouter()


def now() -> datetime:
    return datetime.now(UTC)


def coach_page(
    request: Request,
    db: Session,
    user: User,
    report_id: uuid.UUID | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    config: coach.Config = request.app.state.coach
    settings = coach.settings_of(db, user.id)
    coach.expire_stale(db, user.id, now())
    db.commit()
    reports = coach.reports_of(db, user.id)
    shown = reports[0] if reports else None
    if report_id is not None:
        # The report of someone else does not exist.
        shown = next((report for report in reports if report.id == report_id), None)
        if shown is None:
            raise HTTPException(status_code=404, detail="No such report")
    has_key = settings.encrypted_api_key is not None
    return templates.TemplateResponse(
        request,
        "coach.html",
        {
            "user": user,
            "enabled": settings.enabled_at is not None,
            "has_key": has_key,
            "can_ask": has_key or config.instance_key is not None,
            "left": None
            if has_key
            else max(0, config.per_day - coach.used_today(db, user.id, now())),
            "per_day": config.per_day,
            "reports": reports,
            "shown": shown,
            "underway": any(report.status is ReportStatus.PENDING for report in reports),
            "error": error,
            "days": coach.DAYS,
            "weeks": coach.WEEKS_BEFORE,
        },
        status_code=status_code,
    )


@router.get("/coach")
def coach_home(request: Request, db: Db, user: CurrentUser) -> Response:
    return coach_page(request, db, user)


@router.get("/coach/reports/{report_id}")
def one_report(request: Request, db: Db, user: CurrentUser, report_id: uuid.UUID) -> Response:
    return coach_page(request, db, user, report_id)


@router.get("/coach/figures")
def figures_page(request: Request, db: Db, user: CurrentUser) -> Response:
    """The text to take to a chat with Claude oneself. The app sends nothing."""
    collected = first_day(db, user.id) is not None
    return templates.TemplateResponse(
        request,
        "coach_figures.html",
        {
            "user": user,
            "text": coach.for_chat(db, user.id, today()) if collected else None,
            "days": coach.DAYS,
            "weeks": coach.WEEKS_BEFORE,
        },
    )


@router.get("/coach/figures.txt")
def figures_file(db: Db, user: CurrentUser) -> Response:
    """The same text as a file, for a device on which copying that much is awkward."""
    if first_day(db, user.id) is None:
        raise HTTPException(status_code=404, detail="Nothing has been collected yet")
    day = today()
    return PlainTextResponse(
        coach.for_chat(db, user.id, day),
        headers={"Content-Disposition": f'attachment; filename="figures-{day}.txt"'},
    )


@router.post("/coach/enable")
def enable(db: Db, user: CurrentUser) -> Response:
    settings = coach.stored_settings(db, user.id)
    if settings.enabled_at is None:
        settings.enabled_at = now()
    db.commit()
    return redirect("/coach")


@router.post("/coach/disable")
def disable(db: Db, user: CurrentUser) -> Response:
    """Stop sending anything. Reports stay until the user removes them."""
    settings = coach.stored_settings(db, user.id)
    settings.enabled_at = None
    db.commit()
    return redirect("/coach")


@router.post("/coach/key")
def set_key(
    request: Request, db: Db, user: CurrentUser, api_key: Annotated[str, Form()] = ""
) -> Response:
    settings = coach.stored_settings(db, user.id)
    try:
        coach.set_key(settings, request.app.state.cipher, api_key)
    except CoachError as error:
        return coach_page(request, db, user, error=sentence(error), status_code=400)
    db.commit()
    return redirect("/coach")


@router.post("/coach/key/remove")
def remove_key(db: Db, user: CurrentUser) -> Response:
    settings = coach.stored_settings(db, user.id)
    settings.encrypted_api_key = None
    db.commit()
    return redirect("/coach")


@router.post("/coach/report")
def ask_for_report(
    request: Request, db: Db, user: CurrentUser, background: BackgroundTasks
) -> Response:
    """Start a report. Claude writes it after this request has been answered."""
    config: coach.Config = request.app.state.coach
    cipher = request.app.state.cipher
    try:
        report = coach.request_report(db, user.id, config, cipher, now())
    except CoachError as error:
        db.rollback()
        return coach_page(request, db, user, error=sentence(error), status_code=400)
    if report is not None:
        background.add_task(
            coach.write_pending, request.app.state.sessions, report.id, config, cipher, today()
        )
    return redirect("/coach")


@router.post("/coach/reports/remove")
def remove_reports(db: Db, user: CurrentUser) -> Response:
    db.execute(delete(CoachReport).where(CoachReport.user_id == user.id))
    db.commit()
    return redirect("/coach")
