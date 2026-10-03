"""What the pages of the web interface have in common."""

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from garmin_analyzer.models import User
from garmin_analyzer.sessions import create_session, session_user

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")

COOKIE = "session"
# The longest a browser keeps a cookie. The session itself ends sooner, on the
# server: see sessions.IDLE_LIFETIME.
COOKIE_MAX_AGE = 400 * 24 * 60 * 60
# The longest address the standards allow; keeps the rate limiter's keys small.
MAX_EMAIL_LENGTH = 254


class SignInRequired(Exception):
    """The request needs a signed-in user and has none."""


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session


Db = Annotated[Session, Depends(get_db)]


def signed_in_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get(COOKIE)
    return session_user(db, token) if token else None


def require_user(request: Request, db: Db) -> User:
    user = signed_in_user(request, db)
    if user is None:
        raise SignInRequired
    return user


CurrentUser = Annotated[User, Depends(require_user)]


def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only for the administrator")
    return user


Admin = Annotated[User, Depends(require_admin)]


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def start_session(request: Request, db: Session, user: User) -> RedirectResponse:
    """Sign the user in and send them to the first page. Commits."""
    token = create_session(db, user.id)
    db.commit()
    response = redirect("/")
    response.set_cookie(
        COOKIE,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


def sentence(error: Exception) -> str:
    """An error message as a sentence to show on a page."""
    message = str(error)
    return message[0].upper() + message[1:] + "."
