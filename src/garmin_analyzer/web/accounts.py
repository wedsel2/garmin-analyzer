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
from sqlalchemy.orm import Session

from garmin_analyzer.models import GarminLink, PasswordLink, User
from garmin_analyzer.password_links import LIFETIME, create_link, link_user, use_link
from garmin_analyzer.passwords import MIN_LENGTH, PasswordError, verify_password
from garmin_analyzer.ratelimit import FailureLimiter
from garmin_analyzer.users import NO_PASSWORD, UserError, add_user, normalise_email, set_password
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
    request: Request, db: Session, user: User, error: str | None = None, status_code: int = 200
) -> Response:
    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "user": user,
            "link": db.get(GarminLink, user.id),
            "error": error,
            "min_length": MIN_LENGTH,
        },
        status_code=status_code,
    )


@router.get("/account")
def account(request: Request, db: Db, user: CurrentUser) -> Response:
    return account_page(request, db, user)


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
    # The same count as for signing in, so a session left open somewhere does
    # not give unlimited guesses at the current password.
    failures: FailureLimiter = request.app.state.failures_by_email
    if not failures.attempt(user.email):
        return account_page(
            request, db, user, "Too many failed attempts. Try again in 15 minutes.", 429
        )
    if not verify_password(user.password_hash, current_password):
        return account_page(request, db, user, "The current password is not right.", 400)
    failures.reset(user.email)
    try:
        if password != password_again:
            raise PasswordError("the two new passwords are not the same")
        set_password(db, user, password)
    except PasswordError as error:
        db.rollback()
        return account_page(request, db, user, sentence(error), 400)
    # Every session was ended, this one included; continue in a new one.
    return start_session(request, db, user)
