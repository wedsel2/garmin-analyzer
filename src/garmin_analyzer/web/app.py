"""The web application: setting up an instance, signing in and the first page.

See ADR 8 for accounts and ADR 15 for how sessions and forms are protected.
"""

import hashlib
import logging
from contextlib import suppress
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
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
from garmin_analyzer.sessions import end_session
from garmin_analyzer.tokens import TokenCipher
from garmin_analyzer.users import UserError, add_user, normalise_email, set_password
from garmin_analyzer.web import (
    accounts,
    activity_pages,
    api,
    dashboards,
    garmin_link,
    overview,
    shared,
)
from garmin_analyzer.web.shared import (
    COOKIE,
    HERE,
    MAX_EMAIL_LENGTH,
    CurrentUser,
    Db,
    SignInRequired,
    redirect,
    sentence,
    signed_in_user,
    start_session,
    templates,
)

router = APIRouter()
log = logging.getLogger(__name__)

FAILED_SIGN_INS_PER_EMAIL = 5
FAILED_SIGN_INS_PER_ADDRESS = 20
SIGN_IN_PERIOD_SECONDS = 15 * 60

# Any constant: makes two first-account requests at the same moment take turns.
SETUP_LOCK = 4_815_162_342

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        # The component kit draws some icons from data: addresses in the stylesheet.
        "default-src 'self'; img-src 'self' data:; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
}


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


def untrusted_proxy(request: Request) -> str | None:
    """The address of a proxy whose forwarded headers were not used, if there is one.

    The server puts the client's address from X-Forwarded-For in place of the
    proxy's when it trusts the proxy. So a request that has the header and still
    comes from an address that is not in it passed a proxy that is not trusted.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded is None or request.client is None:
        return None
    addresses = {address.strip() for address in forwarded.split(",")}
    return None if request.client.host in addresses else request.client.host


def warn_about_proxy(request: Request) -> None:
    """Say once that a proxy is not trusted, as nothing else shows it."""
    if request.app.state.proxy_warned:
        return
    proxy = untrusted_proxy(request)
    if proxy is None:
        return
    request.app.state.proxy_warned = True
    log.warning(
        "A request came through a proxy at %s whose forwarded headers are not trusted. "
        "The session cookie is not marked Secure, links to set a password start with "
        "http:// and failed sign-ins of all users are counted together. If that is your "
        "proxy, set FORWARDED_ALLOW_IPS to its address or network.",
        proxy,
    )


async def protect(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Refuse forms posted from other sites and set security headers."""
    warn_about_proxy(request)
    if request.method not in SAFE_METHODS and is_cross_site(request):
        return PlainTextResponse("request from another site refused", status_code=403)
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
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


@router.get("/offline")
def offline(request: Request) -> Response:
    """What the service worker shows without a connection. The same for everyone."""
    return templates.TemplateResponse(request, "offline.html", {})


@router.get("/sw.js")
def service_worker(request: Request) -> Response:
    """The service worker, at the top of the site: it only covers paths below its own.

    A browser stores the offline page when it installs the worker, and installs
    it again only when the script has changed. So the script names the page it
    belongs to, and a release that changes the page replaces the stored one.
    """
    script = (HERE / "static" / "sw.js").read_text(encoding="utf-8")
    page = hashlib.sha256(bytes(offline(request).body)).hexdigest()[:16]
    return Response(f"{script}\n// Offline page {page}\n", media_type="text/javascript")


@router.get("/")
def home(request: Request, db: Db, user: CurrentUser) -> Response:
    link = db.get(GarminLink, user.id)
    today = shared.today()
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "user": user,
            "link": link,
            "today": today,
            "tiles": overview.tiles(db, user.id, today),
            "day_label": overview.day_label,
            "phrase": overview.phrase,
            "series_url": overview.series_url(today),
            "activities": overview.recent_activities(db, user.id),
        },
    )


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
        return setup_page(request, email, sentence(error))
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
    if "hx-request" in request.headers:
        # HTMX would put the sign-in page where part of a page was asked for;
        # this makes it load that page instead.
        return Response(status_code=204, headers={"HX-Redirect": "/login"})
    return redirect("/login")


def create_app(engine: Engine, cipher: TokenCipher) -> FastAPI:
    # The description of the JSON API is served; the pages that render it are not,
    # as they load scripts from elsewhere.
    app = FastAPI(
        title="Garmin Analyzer",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.state.sessions = make_session_factory(engine)
    app.state.cipher = cipher
    app.state.link_attempts = FailureLimiter(
        garmin_link.LINK_ATTEMPTS, garmin_link.LINK_PERIOD_SECONDS
    )
    app.state.failures_by_email = FailureLimiter(FAILED_SIGN_INS_PER_EMAIL, SIGN_IN_PERIOD_SECONDS)
    app.state.failures_by_address = FailureLimiter(
        FAILED_SIGN_INS_PER_ADDRESS, SIGN_IN_PERIOD_SECONDS
    )
    app.state.proxy_warned = False
    app.middleware("http")(protect)
    # The stylesheet holds the whole component kit and shrinks to a fraction.
    app.add_middleware(GZipMiddleware)
    app.add_exception_handler(SignInRequired, to_sign_in)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.include_router(router, include_in_schema=False)
    app.include_router(accounts.router, include_in_schema=False)
    app.include_router(garmin_link.router, include_in_schema=False)
    app.include_router(dashboards.router, include_in_schema=False)
    app.include_router(activity_pages.router, include_in_schema=False)
    app.include_router(api.router)
    return app
