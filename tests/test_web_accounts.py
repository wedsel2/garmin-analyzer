"""Tests for user management by the administrator and for password links."""

import re
import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from garmin_analyzer.models import DailySummary, GarminLink, User
from garmin_analyzer.passwords import verify_password
from garmin_analyzer.tokens import TokenCipher, generate_key
from garmin_analyzer.users import NO_PASSWORD, add_user, set_password
from garmin_analyzer.web.app import FAILED_SIGN_INS_PER_EMAIL, create_app
from garmin_analyzer.web.shared import COOKIE

ADMIN = "admin@example.com"
FRIEND = "friend@example.com"
PASSWORD = "correct horse battery"  # noqa: S105
CIPHER = TokenCipher(generate_key())
LINK = re.compile(r"http://testserver/set-password/([A-Za-z0-9_-]{43})")


def make_client(db: Engine) -> TestClient:
    return TestClient(create_app(db, CIPHER), follow_redirects=False)


@pytest.fixture
def anonymous(db: Engine) -> Iterator[TestClient]:
    with make_client(db) as client:
        yield client


@pytest.fixture
def admin(db: Engine) -> Iterator[TestClient]:
    """A client signed in as the administrator."""
    with Session(db) as session:
        user = add_user(session, ADMIN)
        session.flush()
        set_password(session, user, PASSWORD)
        session.commit()
    with make_client(db) as client:
        assert client.post("/login", data={"email": ADMIN, "password": PASSWORD}).status_code == 303
        yield client


def user_id(db: Engine, email: str) -> uuid.UUID:
    with Session(db) as session:
        return session.scalars(select(User.id).where(User.email == email)).one()


def emails(db: Engine) -> list[str]:
    with Session(db) as session:
        return list(session.scalars(select(User.email).order_by(User.email)))


def invite(admin: TestClient, email: str = FRIEND) -> str:
    """Invite someone and return the path of the link shown to the administrator."""
    page = admin.post("/users", data={"email": email})
    assert page.status_code == 200
    match = LINK.search(page.text)
    assert match is not None
    return f"/set-password/{match.group(1)}"


def accept(client: TestClient, path: str, password: str = PASSWORD) -> int:
    response = client.post(path, data={"password": password, "password_again": password})
    return int(response.status_code)


def test_the_administrator_sees_the_users_and_a_link_to_the_page(admin: TestClient) -> None:
    assert 'href="/users"' in admin.get("/").text

    page = admin.get("/users")

    assert page.status_code == 200
    assert ADMIN in page.text
    assert "Administrator" in page.text
    assert "Active" in page.text


def test_inviting_creates_an_account_and_shows_the_link_once(admin: TestClient, db: Engine) -> None:
    page = admin.post("/users", data={"email": " Friend@Example.com "})

    assert f"Invite for {FRIEND}" in page.text
    assert LINK.search(page.text) is not None
    assert "Invited" in page.text
    with Session(db) as session:
        friend = session.scalars(select(User).where(User.email == FRIEND)).one()
        assert (friend.password_hash, friend.is_admin) == (NO_PASSWORD, False)
    assert LINK.search(admin.get("/users").text) is None


@pytest.mark.parametrize(
    ("email", "message"),
    [(ADMIN, "already exists."), ("no-address", "is not an email address.")],
)
def test_inviting_explains_what_is_wrong(
    admin: TestClient, db: Engine, email: str, message: str
) -> None:
    page = admin.post("/users", data={"email": email})

    assert page.status_code == 400
    assert message in page.text
    assert emails(db) == [ADMIN]


def test_the_invited_person_chooses_a_password_and_is_signed_in(
    admin: TestClient, anonymous: TestClient, db: Engine
) -> None:
    path = invite(admin)

    form = anonymous.get(path)
    assert form.status_code == 200
    assert f"For {FRIEND}" in form.text

    response = anonymous.post(path, data={"password": PASSWORD, "password_again": PASSWORD})

    assert (response.status_code, response.headers["location"]) == (303, "/")
    home = anonymous.get("/")
    assert FRIEND in home.text
    assert 'href="/users"' not in home.text
    with Session(db) as session:
        friend = session.scalars(select(User).where(User.email == FRIEND)).one()
        assert verify_password(friend.password_hash, PASSWORD)
    assert "Active" in admin.get("/users").text


def test_a_link_works_once(admin: TestClient, anonymous: TestClient, db: Engine) -> None:
    path = invite(admin)
    assert accept(anonymous, path) == 303

    with make_client(db) as other:
        assert other.get(path).status_code == 404
        assert "This link no longer works" in other.get(path).text
        assert accept(other, path, "another long password") == 404
        assert COOKIE not in other.cookies
    with Session(db) as session:
        friend = session.scalars(select(User).where(User.email == FRIEND)).one()
        assert verify_password(friend.password_hash, PASSWORD)


def test_an_unknown_link_is_refused(anonymous: TestClient) -> None:
    path = "/set-password/" + "x" * 43

    assert anonymous.get(path).status_code == 404
    assert accept(anonymous, path) == 404


@pytest.mark.parametrize(
    ("password", "again", "message"),
    [
        (PASSWORD, "something else entirely", "The two passwords are not the same."),
        ("short", "short", "Use a password of at least 12 characters."),
    ],
)
def test_a_refused_password_can_be_corrected(
    admin: TestClient, anonymous: TestClient, password: str, again: str, message: str
) -> None:
    path = invite(admin)

    page = anonymous.post(path, data={"password": password, "password_again": again})

    assert page.status_code == 400
    assert message in page.text
    assert COOKIE not in page.cookies
    assert accept(anonymous, path) == 303


def test_a_new_password_link_replaces_the_invite_and_resets_a_password(
    admin: TestClient, anonymous: TestClient, db: Engine
) -> None:
    invited = invite(admin)
    friend = user_id(db, FRIEND)

    page = admin.post(f"/users/{friend}/password-link")
    match = LINK.search(page.text)
    assert match is not None
    renewed = f"/set-password/{match.group(1)}"
    assert f"Invite for {FRIEND}" in page.text
    assert anonymous.get(invited).status_code == 404
    assert accept(anonymous, renewed) == 303

    page = admin.post(f"/users/{friend}/password-link")
    match = LINK.search(page.text)
    assert match is not None
    assert f"Password link for {FRIEND}" in page.text
    assert "Password link sent" in page.text
    # The friend was signed in; a reset signs them out everywhere.
    with make_client(db) as other:
        assert accept(other, f"/set-password/{match.group(1)}", "a brand new password") == 303
    assert anonymous.get("/").headers["location"] == "/login"


def test_removing_a_user_asks_first_and_takes_their_data_along(
    admin: TestClient, anonymous: TestClient, db: Engine
) -> None:
    accept(anonymous, invite(admin))
    friend = user_id(db, FRIEND)
    with Session(db) as session:
        session.add(GarminLink(user_id=friend, encrypted_tokens=b"x"))
        session.add(DailySummary(user_id=friend, calendar_date=date(2026, 10, 1)))
        session.commit()

    question = admin.get(f"/users/{friend}/remove")
    assert question.status_code == 200
    assert f"Remove {FRIEND}?" in question.text
    assert emails(db) == [ADMIN, FRIEND]

    response = admin.post(f"/users/{friend}/remove")

    assert (response.status_code, response.headers["location"]) == (303, "/users")
    assert emails(db) == [ADMIN]
    with Session(db) as session:
        assert session.scalars(select(GarminLink)).all() == []
        assert session.scalars(select(DailySummary)).all() == []
    assert anonymous.get("/").headers["location"] == "/login"


def test_the_administrator_cannot_remove_their_own_account(admin: TestClient, db: Engine) -> None:
    own = user_id(db, ADMIN)

    assert "You cannot remove your own account" in admin.get(f"/users/{own}/remove").text
    assert admin.post(f"/users/{own}/remove").status_code == 400
    assert emails(db) == [ADMIN]


def test_actions_on_a_user_that_does_not_exist_are_refused(admin: TestClient) -> None:
    unknown = uuid.uuid4()

    assert admin.post(f"/users/{unknown}/password-link").status_code == 404
    assert admin.get(f"/users/{unknown}/remove").status_code == 404
    assert admin.post(f"/users/{unknown}/remove").status_code == 404
    assert admin.post("/users/not-an-id/remove").status_code == 422


def test_user_management_is_for_the_administrator_only(
    admin: TestClient, anonymous: TestClient, db: Engine
) -> None:
    own = user_id(db, ADMIN)
    requests = [
        ("GET", "/users"),
        ("POST", "/users"),
        ("POST", f"/users/{own}/password-link"),
        ("GET", f"/users/{own}/remove"),
        ("POST", f"/users/{own}/remove"),
    ]

    for method, path in requests:
        response = anonymous.request(method, path, data={"email": "new@example.com"})
        assert (response.status_code, response.headers["location"]) == (303, "/login")

    accept(anonymous, invite(admin))
    for method, path in requests:
        response = anonymous.request(method, path, data={"email": "new@example.com"})
        assert response.status_code == 403
        assert "set-password" not in response.text
    assert emails(db) == [ADMIN, FRIEND]


def test_forms_for_user_management_cannot_be_posted_from_another_site(
    admin: TestClient, db: Engine
) -> None:
    response = admin.post(
        "/users", data={"email": FRIEND}, headers={"Sec-Fetch-Site": "cross-site"}
    )

    assert response.status_code == 403
    assert emails(db) == [ADMIN]


def change_password(
    client: TestClient, current: str, new: str, again: str | None = None
) -> tuple[int, str]:
    response = client.post(
        "/account/password",
        data={
            "current_password": current,
            "password": new,
            "password_again": new if again is None else again,
        },
    )
    return int(response.status_code), response.text


def test_a_user_changes_their_own_password_and_is_signed_out_elsewhere(
    admin: TestClient, db: Engine
) -> None:
    assert 'href="/account"' in admin.get("/").text
    assert "Change password" in admin.get("/account").text
    with make_client(db) as elsewhere:
        elsewhere.post("/login", data={"email": ADMIN, "password": PASSWORD})
        old_cookie = admin.cookies[COOKIE]

        status, _ = change_password(admin, PASSWORD, "a brand new password")

        assert status == 303
        assert admin.cookies[COOKIE] != old_cookie
        assert admin.get("/").status_code == 200
        assert elsewhere.get("/").headers["location"] == "/login"
        assert (
            elsewhere.post("/login", data={"email": ADMIN, "password": PASSWORD}).status_code == 401
        )
    with Session(db) as session:
        stored = session.scalars(select(User.password_hash)).one()
        assert verify_password(stored, "a brand new password")


@pytest.mark.parametrize(
    ("current", "new", "again", "message"),
    [
        ("not the password!", "a brand new password", None, "The current password is not right."),
        (
            PASSWORD,
            "a brand new password",
            "a brand new passwor",
            "The two new passwords are not the same.",
        ),
        (PASSWORD, "short", None, "Use a password of at least 12 characters."),
    ],
)
def test_a_refused_password_change_changes_nothing(
    admin: TestClient, db: Engine, current: str, new: str, again: str | None, message: str
) -> None:
    status, text = change_password(admin, current, new, again)

    assert status == 400
    assert message in text
    assert admin.get("/").status_code == 200
    with Session(db) as session:
        assert verify_password(session.scalars(select(User.password_hash)).one(), PASSWORD)


def test_guesses_at_the_current_password_are_limited(admin: TestClient, db: Engine) -> None:
    for _ in range(FAILED_SIGN_INS_PER_EMAIL):
        assert change_password(admin, "not the password!", "a brand new password")[0] == 400

    status, text = change_password(admin, PASSWORD, "a brand new password")

    assert status == 429
    assert "Too many failed attempts" in text
    with Session(db) as session:
        assert verify_password(session.scalars(select(User.password_hash)).one(), PASSWORD)


def test_the_account_page_needs_a_signed_in_user(anonymous: TestClient) -> None:
    assert anonymous.get("/account").headers["location"] == "/login"
    response = anonymous.post(
        "/account/password",
        data={"current_password": "x", "password": "y", "password_again": "y"},
    )
    assert response.headers["location"] == "/login"
