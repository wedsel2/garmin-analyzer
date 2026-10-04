"""Tests for the web interface: setting up, signing in and out, and its protections."""

from collections.abc import Iterator

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from garmin_analyzer.db import make_engine
from garmin_analyzer.models import GarminLink, LinkStatus, User, WebSession
from garmin_analyzer.passwords import verify_password
from garmin_analyzer.tokens import TokenCipher, generate_key
from garmin_analyzer.users import NO_PASSWORD, add_user, set_password
from garmin_analyzer.web.app import (
    FAILED_SIGN_INS_PER_ADDRESS,
    FAILED_SIGN_INS_PER_EMAIL,
    create_app,
)
from garmin_analyzer.web.shared import COOKIE

EMAIL = "runner@example.com"
PASSWORD = "correct horse battery"  # noqa: S105
CIPHER = TokenCipher(generate_key())
WRONG = "wrong horse battery"


@pytest.fixture
def client(db: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as client:
        yield client


@pytest.fixture
def account(db: Engine) -> User:
    with Session(db, expire_on_commit=False) as session:
        user = add_user(session, EMAIL)
        session.flush()
        set_password(session, user, PASSWORD)
        session.commit()
        return user


def sign_in(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> int:
    response = client.post("/login", data={"email": email, "password": password})
    return int(response.status_code)


def session_count(db: Engine) -> int:
    with Session(db) as session:
        return session.scalar(select(func.count()).select_from(WebSession)) or 0


def test_healthz_answers_without_signing_in(client: TestClient) -> None:
    response = client.get("/healthz")

    assert (response.status_code, response.text) == (200, "ok")


def test_healthz_reports_a_database_that_is_down() -> None:
    unreachable = make_engine("postgresql+psycopg://nobody@127.0.0.1:1/none")
    with TestClient(create_app(unreachable, CIPHER)) as client:
        assert client.get("/healthz").status_code == 503


def test_a_fresh_instance_leads_to_setup(client: TestClient) -> None:
    assert client.get("/").headers["location"] == "/login"
    assert client.get("/login").headers["location"] == "/setup"
    page = client.get("/setup")
    assert page.status_code == 200
    assert "Create the administrator account" in page.text


def test_setup_creates_the_administrator_and_signs_in(client: TestClient, db: Engine) -> None:
    response = client.post(
        "/setup",
        data={"email": " Runner@Example.com", "password": PASSWORD, "password_again": PASSWORD},
    )

    assert (response.status_code, response.headers["location"]) == (303, "/")
    with Session(db) as session:
        user = session.scalars(select(User)).one()
        assert (user.email, user.is_admin) == (EMAIL, True)
        assert verify_password(user.password_hash, PASSWORD)
    home = client.get("/")
    assert home.status_code == 200
    assert 'href="/account"' in home.text
    assert "No Garmin account is linked yet" in home.text


@pytest.mark.parametrize(
    ("email", "password", "again", "message"),
    [
        (EMAIL, PASSWORD, WRONG, "The two passwords are not the same."),
        (EMAIL, "short", "short", "Use a password of at least 12 characters."),
        ("no-address", PASSWORD, PASSWORD, "is not an email address."),
    ],
)
def test_setup_explains_what_is_wrong(
    client: TestClient, db: Engine, email: str, password: str, again: str, message: str
) -> None:
    response = client.post(
        "/setup", data={"email": email, "password": password, "password_again": again}
    )

    assert response.status_code == 400
    assert message in response.text
    assert COOKIE not in response.cookies
    with Session(db) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


def test_setup_is_closed_once_an_account_exists(
    client: TestClient, db: Engine, account: User
) -> None:
    assert client.get("/setup").headers["location"] == "/login"
    response = client.post(
        "/setup",
        data={"email": "intruder@example.com", "password": PASSWORD, "password_again": PASSWORD},
    )

    assert response.headers["location"] == "/login"
    assert COOKIE not in response.cookies
    with Session(db) as session:
        assert session.scalars(select(User.email)).all() == [EMAIL]


def test_signing_in_and_out(client: TestClient, db: Engine, account: User) -> None:
    assert client.get("/login").status_code == 200

    response = client.post("/login", data={"email": " RUNNER@example.com ", "password": PASSWORD})

    assert (response.status_code, response.headers["location"]) == (303, "/")
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie
    assert client.cookies[COOKIE] not in client.get("/").text
    assert client.get("/login").headers["location"] == "/"

    response = client.post("/logout")

    assert response.headers["location"] == "/login"
    assert session_count(db) == 0
    assert client.get("/").headers["location"] == "/login"


def test_the_cookie_is_secure_over_https(db: Engine, account: User) -> None:
    with TestClient(
        create_app(db, CIPHER), base_url="https://testserver", follow_redirects=False
    ) as client:
        response = client.post("/login", data={"email": EMAIL, "password": PASSWORD})

    assert "Secure" in response.headers["set-cookie"]


def test_a_stolen_cookie_is_useless_after_signing_out(client: TestClient, account: User) -> None:
    sign_in(client)
    token = client.cookies[COOKIE]
    client.post("/logout")

    client.cookies.set(COOKIE, token)

    assert client.get("/").headers["location"] == "/login"


@pytest.mark.parametrize(
    ("email", "password"),
    [(EMAIL, WRONG), ("nobody@example.com", PASSWORD), (EMAIL, " ")],
)
def test_wrong_credentials_get_the_same_answer(
    client: TestClient, db: Engine, account: User, email: str, password: str
) -> None:
    response = client.post("/login", data={"email": email, "password": password})

    assert response.status_code == 401
    assert "Wrong email address or password." in response.text
    assert COOKIE not in response.cookies
    assert session_count(db) == 0


def test_an_account_without_a_password_cannot_sign_in(client: TestClient, db: Engine) -> None:
    with Session(db) as session:
        add_user(session, EMAIL)
        session.commit()

    assert sign_in(client, password=NO_PASSWORD) == 401


def test_sign_in_is_blocked_after_repeated_failures_for_one_account(
    client: TestClient, account: User
) -> None:
    for _ in range(FAILED_SIGN_INS_PER_EMAIL):
        assert sign_in(client, password=WRONG) == 401

    response = client.post("/login", data={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 429
    assert "Too many failed attempts" in response.text
    assert COOKIE not in response.cookies


def test_sign_in_is_blocked_after_repeated_failures_from_one_client(
    client: TestClient, account: User
) -> None:
    for attempt in range(FAILED_SIGN_INS_PER_ADDRESS):
        assert sign_in(client, f"guess{attempt}@example.com") == 401

    assert sign_in(client) == 429


def test_a_successful_sign_in_clears_the_failures_of_the_account(
    client: TestClient, account: User
) -> None:
    for _ in range(FAILED_SIGN_INS_PER_EMAIL - 1):
        sign_in(client, password=WRONG)
    assert sign_in(client) == 303

    for _ in range(FAILED_SIGN_INS_PER_EMAIL - 1):
        assert sign_in(client, password=WRONG) == 401
    assert sign_in(client) == 303


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Sec-Fetch-Site": "same-origin"}, 303),
        ({"Sec-Fetch-Site": "cross-site"}, 403),
        ({"Sec-Fetch-Site": "same-site"}, 403),
        ({"Sec-Fetch-Site": "none"}, 403),
        ({"Origin": "http://testserver"}, 303),
        ({"Origin": "https://evil.example"}, 403),
        ({"Sec-Fetch-Site": "cross-site", "Origin": "http://testserver"}, 403),
    ],
)
def test_forms_posted_from_another_site_are_refused(
    client: TestClient, db: Engine, account: User, headers: dict[str, str], status: int
) -> None:
    response = client.post("/login", data={"email": EMAIL, "password": PASSWORD}, headers=headers)

    assert response.status_code == status
    assert session_count(db) == (1 if status == 303 else 0)


def test_another_site_cannot_sign_someone_out(
    client: TestClient, db: Engine, account: User
) -> None:
    sign_in(client)

    assert client.post("/logout", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert session_count(db) == 1


def test_pages_carry_security_headers_and_are_not_cached(client: TestClient) -> None:
    page = client.get("/setup")

    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert "script-src" not in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["cache-control"] == "no-store"

    icon = client.get("/static/icon.svg")
    assert icon.status_code == 200
    assert icon.headers.get("cache-control") != "no-store"


def test_answers_are_compressed_for_browsers_that_accept_it(client: TestClient) -> None:
    page = client.get("/setup", headers={"Accept-Encoding": "gzip"})

    assert page.headers["content-encoding"] == "gzip"
    assert "Create the administrator account" in page.text


def test_input_is_escaped_on_the_page(client: TestClient, account: User) -> None:
    response = client.post(
        "/login", data={"email": '"><script>alert(1)</script>', "password": WRONG}
    )

    assert "<script>" not in response.text


def test_home_shows_only_the_link_of_the_signed_in_user(
    client: TestClient, db: Engine, account: User
) -> None:
    sign_in(client)
    with Session(db) as session:
        other = add_user(session, "cyclist@example.com")
        session.flush()
        session.add(
            GarminLink(user_id=other.id, encrypted_tokens=b"x", status=LinkStatus.NEEDS_RELINK)
        )
        session.commit()
    assert "No Garmin account is linked yet" in client.get("/").text

    with Session(db) as session:
        session.add(GarminLink(user_id=account.id, encrypted_tokens=b"x"))
        session.commit()
    home = client.get("/").text
    assert "No Garmin account is linked yet" not in home
    assert "Garmin no longer accepts the link" not in home
    assert "Nothing has been collected yet" in client.get("/account").text

    with Session(db) as session:
        link = session.get_one(GarminLink, account.id)
        link.status = LinkStatus.NEEDS_RELINK
        session.commit()
    assert "Garmin no longer accepts the link" in client.get("/").text


def test_signing_in_upgrades_a_hash_made_with_older_settings(
    client: TestClient, db: Engine, account: User
) -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=1024).hash(PASSWORD)
    with Session(db) as session:
        session.get_one(User, account.id).password_hash = weak
        session.commit()

    assert sign_in(client) == 303

    with Session(db) as session:
        upgraded = session.get_one(User, account.id).password_hash
    assert upgraded != weak
    assert verify_password(upgraded, PASSWORD)


def test_signing_out_without_a_session_is_harmless(client: TestClient) -> None:
    assert client.post("/logout").headers["location"] == "/login"
