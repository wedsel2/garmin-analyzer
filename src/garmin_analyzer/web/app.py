"""The web application: setting up an instance, signing in and the first page.

See ADR 8 for accounts and ADR 15 for how sessions and forms are protected.
"""

from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Form, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.base import RequestResponseEndpoint

from garmin_analyzer.db import make_session_factory
from garmin_analyzer.models import GarminLink, User
from garmin_analyzer.passwords import (
    MIN_LENGTH,
    PasswordError,
    hash_password,
    needs_rehash,
    verify_password,
)
from garmin_analyzer.ratelimit import FailureLimiter
from garmin_analyzer.sessions import create_session, end_session, session_user
from garmin_analyzer.users import UserError, add_user, normalise_email, set_password

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")
router = APIRouter()

COOKIE = "session"
# The longest a browser keeps a cookie. The session itself ends sooner, on the
# server: see sessions.IDLE_LIFETIME.
COOKIE_MAX_AGE = 400 * 24 * 60 * 60
# The longest address the standards allow; keeps the rate limiter's keys small.
MAX_EMAIL_LENGTH = 254

FAILED_SIGN_INS_PER_EMAIL = 5
FAILED_SIGN_INS_PER_ADDRESS = 20
SIGN_IN_PERIOD_SECONDS = 15 * 60

# Any constant: makes two first-account requests at the same moment take turns.
SETUP_LOCK = 4_815_162_342

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
}


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


def is_cross_site(request: Request) -> bool:
    """True when a browser says the request was started by another site.

    Browsers state where a request comes from in Sec-Fetch-Site, and older ones
    in Origin. A request with neither is not from a browser, so it cannot be
    riding on someone's session cookie.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site != "same-origin"
    origin = request.headers.get("origin")
    if origin is None:
        return False
    return urlsplit(origin).netloc != request.headers.get("host")


async def protect(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Refuse forms posted from other sites and set security headers."""
    if request.method not in SAFE_METHODS and is_cross_site(request):
        return PlainTextResponse("request from another site refused", status_code=403)
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


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


def has_users(db: Session) -> bool:
    return db.scalar(select(User.id).limit(1)) is not None


@router.get("/healthz")
def healthz(db: Db) -> PlainTextResponse:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return PlainTextResponse("database unreachable", status_code=503)
    return PlainTextResponse("ok")


@router.get("/")
def home(request: Request, db: Db, user: CurrentUser) -> Response:
    link = db.get(GarminLink, user.id)
    return templates.TemplateResponse(request, "home.html", {"user": user, "link": link})


def setup_page(request: Request, email: str = "", error: str | None = None) -> Response:
    return templates.TemplateResponse(
        request,
        "setup.html",
        {"email": email, "error": error, "min_length": MIN_LENGTH},
        status_code=400 if error else 200,
    )


@router.get("/setup")
def setup_form(request: Request, db: Db) -> Response:
    if has_users(db):
        return redirect("/login")
    return setup_page(request)


@router.post("/setup")
def setup(
    request: Request,
    db: Db,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password_again: Annotated[str, Form()],
) -> Response:
    """Create the first account of the instance, which is its administrator."""
    db.execute(select(func.pg_advisory_xact_lock(SETUP_LOCK)))
    if has_users(db):
        return redirect("/login")
    try:
        if password != password_again:
            raise PasswordError("the two passwords are not the same")
        user = add_user(db, normalise_email(email)[:MAX_EMAIL_LENGTH])
        # Gives the user its id.
        db.flush()
        set_password(db, user, password)
    except (UserError, PasswordError) as error:
        db.rollback()
        message = str(error)
        return setup_page(request, email, message[0].upper() + message[1:] + ".")
    return start_session(request, db, user)


def login_page(
    request: Request, email: str = "", error: str | None = None, status_code: int = 200
) -> Response:
    return templates.TemplateResponse(
        request, "login.html", {"email": email, "error": error}, status_code=status_code
    )


@router.get("/login")
def login_form(request: Request, db: Db) -> Response:
    if not has_users(db):
        return redirect("/setup")
    if signed_in_user(request, db) is not None:
        return redirect("/")
    return login_page(request)


@router.post("/login")
def login(
    request: Request,
    db: Db,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    email = normalise_email(email)[:MAX_EMAIL_LENGTH]
    address = request.client.host if request.client else "unknown"
    by_email: FailureLimiter = request.app.state.failures_by_email
    by_address: FailureLimiter = request.app.state.failures_by_address
    # Counted as failed before the password is checked: see FailureLimiter.attempt.
    if not by_address.attempt(address) or not by_email.attempt(email):
        return login_page(request, email, "Too many failed attempts. Try again in 15 minutes.", 429)

    user = db.scalar(select(User).where(User.email == email))
    matches = verify_password(user.password_hash if user else None, password)
    if user is None or not matches:
        return login_page(request, email, "Wrong email address or password.", 401)

    by_email.reset(email)
    by_address.forgive(address)
    if needs_rehash(user.password_hash):
        # Not possible for a password that the current rules would refuse.
        with suppress(PasswordError):
            user.password_hash = hash_password(password)
    return start_session(request, db, user)


@router.post("/logout")
def logout(request: Request, db: Db) -> Response:
    token = request.cookies.get(COOKIE)
    if token:
        end_session(db, token)
        db.commit()
    response = redirect("/login")
    response.delete_cookie(COOKIE)
    return response


def to_sign_in(request: Request, error: Exception) -> Response:
    return redirect("/login")


def create_app(engine: Engine) -> FastAPI:
    # No JSON API yet, so nothing to document.
    app = FastAPI(title="Garmin Analyzer", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.sessions = make_session_factory(engine)
    app.state.failures_by_email = FailureLimiter(FAILED_SIGN_INS_PER_EMAIL, SIGN_IN_PERIOD_SECONDS)
    app.state.failures_by_address = FailureLimiter(
        FAILED_SIGN_INS_PER_ADDRESS, SIGN_IN_PERIOD_SECONDS
    )
    app.middleware("http")(protect)
    app.add_exception_handler(SignInRequired, to_sign_in)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.include_router(router)
    return app
