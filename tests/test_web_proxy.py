"""Tests for the web interface behind a proxy, such as a Cloudflare tunnel.

`serve` lets uvicorn read the forwarded headers of proxies named in
FORWARDED_ALLOW_IPS. These tests put the same middleware around the application,
with the test client in the place of the proxy.
"""

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from garmin_analyzer.tokens import TokenCipher, generate_key
from garmin_analyzer.users import add_user, set_password
from garmin_analyzer.web.app import FAILED_SIGN_INS_PER_ADDRESS, PROXY_WARNINGS, create_app
from garmin_analyzer.web.shared import COOKIE

ADMIN = "admin@example.com"
PASSWORD = "correct horse battery"  # noqa: S105
WRONG = "wrong horse battery"
CIPHER = TokenCipher(generate_key())
# The address the test client connects from.
PROXY = "testclient"
VISITOR = "203.0.113.7"
OTHER_VISITOR = "203.0.113.8"
PUBLIC = "http://garmin.example.com"


def forwarded(visitor: str = VISITOR) -> dict[str, str]:
    """What a proxy adds to a request that reached it over HTTPS."""
    return {"X-Forwarded-Proto": "https", "X-Forwarded-For": visitor}


@pytest.fixture(autouse=True)
def administrator(db: Engine) -> None:
    with Session(db) as session:
        user = add_user(session, ADMIN)
        session.flush()
        set_password(session, user, PASSWORD)
        session.commit()


@pytest.fixture
def trusted(db: Engine) -> Iterator[TestClient]:
    """A client that is a proxy whose forwarded headers are trusted."""
    app = create_app(db, CIPHER)
    # Added last, so it is the first to see a request, as in uvicorn.
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=PROXY)
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as client:
        yield client


@pytest.fixture
def untrusted(db: Engine) -> Iterator[TestClient]:
    """A client that is a proxy nobody has named in FORWARDED_ALLOW_IPS."""
    with TestClient(create_app(db, CIPHER), base_url=PUBLIC, follow_redirects=False) as client:
        yield client


def sign_in(client: TestClient, email: str = ADMIN, password: str = PASSWORD) -> str:
    """Sign in through the proxy and return the Set-Cookie header."""
    response = client.post(
        "/login", data={"email": email, "password": password}, headers=forwarded()
    )
    assert response.status_code == 303
    return response.headers["set-cookie"]


def test_the_session_cookie_is_secure_behind_a_trusted_proxy(trusted: TestClient) -> None:
    assert "; Secure" in sign_in(trusted)


def test_a_password_link_has_the_public_address_behind_a_trusted_proxy(
    trusted: TestClient,
) -> None:
    sign_in(trusted)
    # The test client talks plain HTTP, so it does not send a Secure cookie by itself.
    session = {"Cookie": f"{COOKIE}={trusted.cookies[COOKIE]}"}

    page = trusted.post(
        "/users", data={"email": "friend@example.com"}, headers=forwarded() | session
    )

    assert page.status_code == 200
    assert "https://garmin.example.com/set-password/" in page.text


def test_failed_sign_ins_are_counted_per_visitor_behind_a_trusted_proxy(
    trusted: TestClient,
) -> None:
    def attempt(number: int, visitor: str) -> int:
        response = trusted.post(
            "/login",
            data={"email": f"nobody{number}@example.com", "password": WRONG},
            headers=forwarded(visitor),
        )
        return int(response.status_code)

    for number in range(FAILED_SIGN_INS_PER_ADDRESS):
        assert attempt(number, VISITOR) == 401

    assert attempt(FAILED_SIGN_INS_PER_ADDRESS, VISITOR) == 429
    assert attempt(FAILED_SIGN_INS_PER_ADDRESS, OTHER_VISITOR) == 401


def test_a_visitor_cannot_choose_the_address_that_is_counted(trusted: TestClient) -> None:
    """A proxy puts the address it saw last; what the visitor sent comes before it."""

    def attempt(number: int) -> int:
        response = trusted.post(
            "/login",
            data={"email": f"nobody{number}@example.com", "password": WRONG},
            headers=forwarded(f"198.51.100.{number}, {VISITOR}"),
        )
        return int(response.status_code)

    for number in range(FAILED_SIGN_INS_PER_ADDRESS):
        assert attempt(number) == 401

    assert attempt(FAILED_SIGN_INS_PER_ADDRESS) == 429


def test_a_trusted_proxy_and_a_direct_visitor_give_no_warning(
    trusted: TestClient, untrusted: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        trusted.get("/login", headers=forwarded())
        untrusted.get("/login")

    assert caplog.messages == []


def test_a_trusted_proxy_that_adds_a_header_of_its_own_gives_no_warning(
    trusted: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The server reads the last X-Forwarded-For; the visitor may have sent one before it."""
    lines = [("X-Forwarded-For", "198.51.100.1"), ("X-Forwarded-For", VISITOR)]

    with caplog.at_level(logging.WARNING):
        trusted.get("/login", headers=lines)
        trusted.get("/login", headers={"X-Forwarded-For": ""})

    assert caplog.messages == []


def test_every_proxy_that_is_not_trusted_is_named_up_to_a_number(
    db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(db, CIPHER)

    with caplog.at_level(logging.WARNING):
        for number in range(PROXY_WARNINGS + 2):
            with TestClient(app, client=(f"10.0.0.{number}", 50000)) as client:
                client.get("/login", headers=forwarded())

    assert len(caplog.messages) == PROXY_WARNINGS
    assert "a proxy at 10.0.0.0 " in caplog.messages[0]
    assert "a proxy at 10.0.0.1 " in caplog.messages[1]


def test_a_proxy_that_is_not_trusted_is_named_once_in_the_log(
    untrusted: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        cookie = sign_in(untrusted)
        untrusted.get("/login", headers=forwarded(OTHER_VISITOR))

    assert "Secure" not in cookie
    [message] = caplog.messages
    assert f"a proxy at {PROXY} whose forwarded headers are not trusted" in message
    assert "FORWARDED_ALLOW_IPS" in message
