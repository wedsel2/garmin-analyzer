"""Tests for linking Garmin from the browser. Garmin is replaced by a fake."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from garmin_analyzer.db import make_session_factory
from garmin_analyzer.garmin import GarminSession, LinkError
from garmin_analyzer.links import OTHER_ACCOUNT, sync_lock
from garmin_analyzer.models import GarminLink, LinkStatus, User
from garmin_analyzer.tokens import TokenCipher, generate_key
from garmin_analyzer.users import add_user, set_password
from garmin_analyzer.web.app import create_app
from garmin_analyzer.web.garmin_link import LINK_ATTEMPTS

EMAIL = "runner@example.com"
PASSWORD = "correct horse battery"  # noqa: S105
CIPHER = TokenCipher(generate_key())
PASTED = "https://sso.garmin.com/sso/embed?ticket=ST-0123456-abcDEF-sso"


class StubGarmin(GarminSession):
    def __init__(self, tokens: str = "linked-tokens") -> None:
        self._tokens = tokens

    def tokens(self) -> str:
        return self._tokens

    def account_id(self) -> int | None:
        return None


@pytest.fixture
def pasted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What was handed to the ticket exchange, which always succeeds."""
    seen: list[str] = []

    def from_ticket(text: str) -> GarminSession:
        seen.append(text)
        return StubGarmin()

    monkeypatch.setattr(GarminSession, "from_ticket", from_ticket)
    return seen


def refuse_tickets(monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(text: str) -> GarminSession:
        raise LinkError("Garmin refused the ticket; it may have expired or been used already")

    monkeypatch.setattr(GarminSession, "from_ticket", refused)


@pytest.fixture
def user(db: Engine) -> User:
    with Session(db, expire_on_commit=False) as session:
        user = add_user(session, EMAIL)
        session.flush()
        set_password(session, user, PASSWORD)
        session.commit()
        return user


@pytest.fixture
def client(db: Engine, user: User) -> Iterator[TestClient]:
    """A client signed in as the user."""
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as client:
        assert client.post("/login", data={"email": EMAIL, "password": PASSWORD}).status_code == 303
        yield client


def stored_link(db: Engine) -> GarminLink | None:
    with Session(db) as session:
        return session.scalars(select(GarminLink)).one_or_none()


def test_the_overview_leads_to_the_page_that_explains_linking(client: TestClient) -> None:
    assert 'href="/garmin"' in client.get("/").text

    page = client.get("/garmin")

    assert page.status_code == 200
    assert 'href="https://sso.garmin.com/sso/signin?' in page.text
    assert 'rel="noopener noreferrer"' in page.text
    assert "never sees your Garmin password" in page.text


def test_pasting_the_address_links_the_account(
    client: TestClient, db: Engine, pasted: list[str]
) -> None:
    response = client.post("/garmin/link", data={"address": PASTED})

    assert (response.status_code, response.headers["location"]) == (303, "/")
    assert pasted == [PASTED]
    link = stored_link(db)
    assert link is not None
    assert link.status is LinkStatus.ACTIVE
    assert CIPHER.decrypt(link.encrypted_tokens) == "linked-tokens"
    assert b"linked-tokens" not in link.encrypted_tokens
    home = client.get("/").text
    assert "Nothing has been collected yet" in home
    assert 'href="/garmin"' not in home


def test_a_refused_ticket_is_explained_and_nothing_is_stored(
    client: TestClient, db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    refuse_tickets(monkeypatch)

    page = client.post("/garmin/link", data={"address": PASTED})

    assert page.status_code == 400
    assert "Garmin refused the ticket; it may have expired or been used already." in page.text
    assert stored_link(db) is None


def test_an_address_without_a_ticket_never_reaches_garmin(client: TestClient, db: Engine) -> None:
    # Not faked: without a ticket the real exchange stops before any request.
    page = client.post("/garmin/link", data={"address": "https://sso.garmin.com/sso/embed"})

    assert page.status_code == 400
    assert "No ticket found" in page.text
    assert stored_link(db) is None


def test_linking_again_makes_a_link_that_needed_it_active(
    client: TestClient, db: Engine, user: User, pasted: list[str]
) -> None:
    with Session(db) as session:
        session.add(
            GarminLink(
                user_id=user.id,
                encrypted_tokens=CIPHER.encrypt("old-tokens"),
                garmin_account_id=42,
                status=LinkStatus.NEEDS_RELINK,
                last_error="rejected",
            )
        )
        session.commit()
    assert "Sign in to Garmin again" in client.get("/").text
    assert "Garmin no longer accepts the link" in client.get("/garmin").text

    assert client.post("/garmin/link", data={"address": PASTED}).status_code == 303

    link = stored_link(db)
    assert link is not None
    assert (link.status, link.last_error, link.garmin_account_id) == (LinkStatus.ACTIVE, None, 42)
    assert CIPHER.decrypt(link.encrypted_tokens) == "linked-tokens"
    assert "A Garmin account is linked" in client.get("/garmin").text


def test_a_link_to_another_garmin_account_is_explained(
    client: TestClient, db: Engine, user: User
) -> None:
    with Session(db) as session:
        session.add(
            GarminLink(
                user_id=user.id,
                encrypted_tokens=b"x",
                status=LinkStatus.NEEDS_RELINK,
                last_error=OTHER_ACCOUNT,
            )
        )
        session.commit()

    assert "is not the one your data came from" in client.get("/garmin").text


def test_linking_waits_for_a_running_sync_without_spending_the_ticket(
    client: TestClient, db: Engine, user: User, pasted: list[str]
) -> None:
    with make_session_factory(db)() as other, sync_lock(other, user.id):
        page = client.post("/garmin/link", data={"address": PASTED})

    assert page.status_code == 409
    assert "Your data is being collected right now" in page.text
    assert pasted == []
    assert stored_link(db) is None

    assert client.post("/garmin/link", data={"address": PASTED}).status_code == 303


def test_the_sync_lock_is_free_again_after_linking(
    client: TestClient, db: Engine, user: User, pasted: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post("/garmin/link", data={"address": PASTED})
    refuse_tickets(monkeypatch)
    client.post("/garmin/link", data={"address": PASTED})

    with make_session_factory(db)() as other, sync_lock(other, user.id):
        pass


def test_attempts_are_limited_to_keep_garmin_from_banning_the_server(
    client: TestClient, db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    refuse_tickets(monkeypatch)
    for _ in range(LINK_ATTEMPTS):
        assert client.post("/garmin/link", data={"address": PASTED}).status_code == 400

    reached: list[str] = []
    monkeypatch.setattr(GarminSession, "from_ticket", reached.append)
    page = client.post("/garmin/link", data={"address": PASTED})

    assert page.status_code == 429
    assert "Too many attempts" in page.text
    assert reached == []


def test_a_user_links_only_their_own_account(
    client: TestClient, db: Engine, user: User, pasted: list[str]
) -> None:
    with Session(db) as session:
        other = add_user(session, "cyclist@example.com")
        session.flush()
        session.add(GarminLink(user_id=other.id, encrypted_tokens=CIPHER.encrypt("theirs")))
        session.commit()
        other_id = other.id

    client.post("/garmin/link", data={"address": PASTED})

    with Session(db) as session:
        assert CIPHER.decrypt(session.get_one(GarminLink, other_id).encrypted_tokens) == "theirs"
        assert CIPHER.decrypt(session.get_one(GarminLink, user.id).encrypted_tokens) == (
            "linked-tokens"
        )


def test_linking_needs_a_signed_in_user_and_the_same_site(
    db: Engine, client: TestClient, pasted: list[str]
) -> None:
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as anonymous:
        assert anonymous.get("/garmin").headers["location"] == "/login"
        response = anonymous.post("/garmin/link", data={"address": PASTED})
        assert response.headers["location"] == "/login"

    response = client.post(
        "/garmin/link", data={"address": PASTED}, headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 403
    assert pasted == []
    assert stored_link(db) is None
