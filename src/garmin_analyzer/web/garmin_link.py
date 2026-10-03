"""Linking a Garmin account from the browser.

The user signs in at Garmin in their own browser and pastes the resulting
address here; the app only exchanges the ticket in it for tokens (ADR 9).
"""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from garmin_analyzer.garmin import SIGN_IN_URL, GarminSession, LinkError, extract_ticket
from garmin_analyzer.links import OTHER_ACCOUNT, AlreadySyncing, store_link, sync_lock
from garmin_analyzer.models import GarminLink, LinkStatus, User
from garmin_analyzer.ratelimit import FailureLimiter
from garmin_analyzer.web.shared import CurrentUser, Db, redirect, sentence, templates

router = APIRouter()

# An address with a ticket is a few hundred characters.
MAX_PASTED_LENGTH = 2000
# Every attempt is a request to Garmin's sign-in site from this server's
# address, which Garmin bans when it sees too many.
LINK_ATTEMPTS = 5
LINK_PERIOD_SECONDS = 15 * 60


def link_page(
    request: Request, db: Session, user: User, error: str | None = None, status_code: int = 200
) -> Response:
    link = db.get(GarminLink, user.id)
    return templates.TemplateResponse(
        request,
        "garmin.html",
        {
            "user": user,
            "link": link,
            "other_account": link is not None and link.last_error == OTHER_ACCOUNT,
            "needs_relink": link is not None and link.status is LinkStatus.NEEDS_RELINK,
            "sign_in_url": SIGN_IN_URL,
            "error": error,
        },
        status_code=status_code,
    )


@router.get("/garmin")
def garmin(request: Request, db: Db, user: CurrentUser) -> Response:
    return link_page(request, db, user)


@router.post("/garmin/link")
def link(request: Request, db: Db, user: CurrentUser, address: Annotated[str, Form()]) -> Response:
    """Exchange the ticket in the pasted address for tokens and store them."""
    address = address[:MAX_PASTED_LENGTH]
    try:
        # Checked first: a wrong paste goes nowhere near Garmin, so it is not
        # counted as an attempt.
        extract_ticket(address)
    except LinkError as error:
        return link_page(request, db, user, sentence(error), status_code=400)
    attempts: FailureLimiter = request.app.state.link_attempts
    key = str(user.id)
    if not attempts.attempt(key):
        return link_page(
            request, db, user, "Too many attempts. Try again in 15 minutes.", status_code=429
        )
    try:
        # A running sync would store its own tokens over the new ones when it
        # ends. The lock is taken only now, not while the user signs in.
        with sync_lock(db, user.id):
            linked = GarminSession.from_ticket(address)
            store_link(db, user.id, request.app.state.cipher, linked)
            db.commit()
    except AlreadySyncing:
        attempts.forgive(key)
        return link_page(
            request,
            db,
            user,
            "Your data is being collected right now. Wait until that has ended, "
            "then sign in to Garmin again for a new address.",
            status_code=409,
        )
    except LinkError as error:
        db.rollback()
        return link_page(request, db, user, sentence(error), status_code=400)
    attempts.reset(key)
    return redirect("/")
