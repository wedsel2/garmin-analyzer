"""Managing users, for the administrator, and setting a password: from a link or your own.

The administrator sees accounts, never the health data of other users (ADR 8).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from garmin_analyzer.models import GarminLink, LinkStatus, PasswordLink, User
from garmin_analyzer.password_links import LIFETIME, create_link, link_user, use_link
from garmin_analyzer.passwords import MIN_LENGTH, PasswordError, verify_password
from garmin_analyzer.ratelimit import FailureLimiter
from garmin_analyzer.users import (
    MAX_NAME_LENGTH,
    NO_PASSWORD,
    UserError,
    add_user,
    change_email,
    normalise_email,
    set_name,
    set_password,
)
from garmin_analyzer.web.shared import (
    MAX_EMAIL_LENGTH,
    Admin,
    CurrentUser,
    Db,
    redirect,
    sentence,
    start_session,
    templates,
)

router = APIRouter()


@dataclass
class NewLink:
    """A link that was just made. Its address can only be shown now."""

    email: str
    address: str
    is_invite: bool


@dataclass
class Row:
    user: User
    state: str


def user_rows(db: Session) -> list[Row]:
    now = datetime.now(UTC)
    pending = set(db.scalars(select(PasswordLink.user_id).where(PasswordLink.expires_at > now)))
    rows = []
    for user in db.scalars(select(User).order_by(User.email)):
        if user.password_hash != NO_PASSWORD:
            state = "Password link sent" if user.id in pending else "Active"
        else:
            state = "Invited" if user.id in pending else "No password"
        rows.append(Row(user, state))
    return rows


def users_page(
    request: Request,
    db: Session,
    admin: User,
    new_link: NewLink | None = None,
    error: str | None = None,
    email: str = "",
) -> Response:
    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "user": admin,
            "rows": user_rows(db),
            "new_link": new_link,
            "error": error,
            "email": email,
            "days": LIFETIME.days,
        },
        status_code=400 if error else 200,
    )


def new_link(request: Request, db: Session, user: User) -> NewLink:
    """Make a password link for a user. Commits."""
    is_invite = user.password_hash == NO_PASSWORD
    token = create_link(db, user.id)
    db.commit()
    return NewLink(user.email, f"{request.base_url}set-password/{token}", is_invite)


@router.get("/users")
def users(request: Request, db: Db, admin: Admin) -> Response:
    return users_page(request, db, admin)


@router.post("/users")
def invite(request: Request, db: Db, admin: Admin, email: Annotated[str, Form()]) -> Response:
    """Create an account without a password and the link to set one."""
    try:
        user = add_user(db, normalise_email(email)[:MAX_EMAIL_LENGTH])
    except UserError as error:
        return users_page(request, db, admin, error=sentence(error), email=email)
    # Gives the user its id.
    db.flush()
    return users_page(request, db, admin, new_link(request, db, user))


def find_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No such user")
    return user


@router.post("/users/{user_id}/password-link")
def password_link(request: Request, db: Db, admin: Admin, user_id: uuid.UUID) -> Response:
    """Make a new link for a user who lost their password or whose invite ran out."""
    user = find_user(db, user_id)
    return users_page(request, db, admin, new_link(request, db, user))


@router.get("/users/{user_id}/remove")
def remove_form(request: Request, db: Db, admin: Admin, user_id: uuid.UUID) -> Response:
    target = find_user(db, user_id)
    return templates.TemplateResponse(
        request, "user_remove.html", {"user": admin, "target": target}
    )


@router.post("/users/{user_id}/remove")
def remove(db: Db, admin: Admin, user_id: uuid.UUID) -> Response:
    """Remove a user and, through the foreign keys, everything stored for them."""
    target = find_user(db, user_id)
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot remove your own account")
    db.delete(target)
    db.commit()
    return redirect("/users")


def set_password_page(
    request: Request, token: str, email: str, error: str | None = None
) -> Response:
    return templates.TemplateResponse(
        request,
        "set_password.html",
        {"token": token, "email": email, "error": error, "min_length": MIN_LENGTH},
        status_code=400 if error else 200,
    )


def link_invalid(request: Request) -> Response:
    return templates.TemplateResponse(request, "link_invalid.html", {}, status_code=404)


@router.get("/set-password/{token}")
def set_password_form(request: Request, db: Db, token: str) -> Response:
    user = link_user(db, token)
    if user is None:
        return link_invalid(request)
    return set_password_page(request, token, user.email)


@router.post("/set-password/{token}")
def set_password_from_link(
    request: Request,
    db: Db,
    token: str,
    password: Annotated[str, Form()],
    password_again: Annotated[str, Form()],
) -> Response:
    """Set the password the link is for, spend the link and sign the user in."""
    try:
        if password != password_again:
            raise PasswordError("the two passwords are not the same")
        user = use_link(db, token, password)
    except PasswordError as error:
        db.rollback()
        owner = link_user(db, token)
        if owner is None:
            return link_invalid(request)
        return set_password_page(request, token, owner.email, sentence(error))
    if user is None:
        return link_invalid(request)
    return start_session(request, db, user)


def account_page(
    request: Request,
    db: Session,
    user: User,
    *,
    profile_error: str | None = None,
    password_error: str | None = None,
    status_code: int = 200,
    name: str | None = None,
    email: str | None = None,
    saved: bool = False,
) -> Response:
    """The account page. A refused profile form comes back with what was entered."""
    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "user": user,
            "link": db.get(GarminLink, user.id),
            "collect_periods": COLLECT_PERIODS,
            "name": (user.name or "") if name is None else name,
            "email": user.email if email is None else email,
            "saved": saved,
            "profile_error": profile_error,
            "password_error": password_error,
            "min_length": MIN_LENGTH,
            "max_name_length": MAX_NAME_LENGTH,
        },
        status_code=status_code,
    )


@router.get("/account")
def account(request: Request, db: Db, user: CurrentUser, saved: str = "") -> Response:
    return account_page(request, db, user, saved=bool(saved))


# What the account page offers to load again, as days back from today. Every
# day is some twenty requests to Garmin, so the longest takes about ten minutes.
COLLECT_PERIODS = {3: "Last 3 days", 7: "Last week", 14: "Last 2 weeks", 28: "Last 4 weeks"}


@router.post("/account/collect")
def request_collect(db: Db, user: CurrentUser, days: Annotated[int, Form()] = 3) -> Response:
    """Ask the worker to collect your data now instead of at the next round."""
    if days not in COLLECT_PERIODS:
        raise HTTPException(status_code=400, detail="Not a period that can be collected")
    link = db.get(GarminLink, user.id)
    if link is None or link.status is not LinkStatus.ACTIVE:
        # Nothing can be collected until the account is linked, or linked again.
        return redirect("/garmin")
    if link.sync_requested_at is None:
        link.sync_requested_at = datetime.now(UTC)
        link.sync_requested_days = days
        db.commit()
    return redirect("/account")


def refuse_current_password(request: Request, user: User, password: str) -> tuple[str, int] | None:
    """Why the current password is not accepted and the status to answer with, if it is not."""
    # The same count as for signing in, so a session left open somewhere does
    # not give unlimited guesses at the current password.
    failures: FailureLimiter = request.app.state.failures_by_email
    if not failures.attempt(user.email):
        return "Too many failed attempts. Try again in 15 minutes.", 429
    if not verify_password(user.password_hash, password):
        return "The current password is not right.", 400
    failures.reset(user.email)
    return None


@router.post("/account/profile")
def change_profile(
    request: Request,
    db: Db,
    user: CurrentUser,
    email: Annotated[str, Form()],
    name: Annotated[str, Form()] = "",
    current_password: Annotated[str, Form()] = "",
) -> Response:
    """Change your own name and email address. Another address needs the current password."""

    def refused(error: str, status_code: int = 400) -> Response:
        return account_page(
            request,
            db,
            user,
            profile_error=error,
            status_code=status_code,
            name=name,
            email=email,
        )

    new_email = normalise_email(email)[:MAX_EMAIL_LENGTH]
    if new_email != user.email:
        # The address is what you sign in with: a session left open somewhere
        # must not be enough to take the account over.
        wrong = refuse_current_password(request, user, current_password)
        if wrong is not None:
            return refused(*wrong)
    try:
        change_email(db, user, new_email)
        set_name(user, name)
        db.commit()
    except UserError as error:
        db.rollback()
        return refused(sentence(error))
    except IntegrityError:
        # Someone else took the address between the check and the commit.
        db.rollback()
        return refused(f"A user with email {new_email} already exists.")
    return redirect("/account?saved=1")


@router.post("/account/password")
def change_password(
    request: Request,
    db: Db,
    user: CurrentUser,
    current_password: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password_again: Annotated[str, Form()],
) -> Response:
    """Change your own password. Signs you out everywhere else."""
    refused = refuse_current_password(request, user, current_password)
    if refused is not None:
        return account_page(request, db, user, password_error=refused[0], status_code=refused[1])
    try:
        if password != password_again:
            raise PasswordError("the two new passwords are not the same")
        set_password(db, user, password)
    except PasswordError as error:
        db.rollback()
        return account_page(request, db, user, password_error=sentence(error), status_code=400)
    # Every session was ended, this one included; continue in a new one.
    return start_session(request, db, user)
