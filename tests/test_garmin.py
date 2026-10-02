"""Tests for the Garmin wrapper. The library is replaced by a fake: no test contacts Garmin."""

from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

import pytest
from garminconnect import GarminConnectAuthenticationError, GarminConnectConnectionError

from garmin_analyzer import garmin
from garmin_analyzer.garmin import (
    SIGN_IN_URL,
    SSO_EMBED,
    GarminSession,
    LinkError,
    RelinkRequired,
    extract_ticket,
)

TOKENS = '{"di_token": "access", "di_refresh_token": "refresh", "di_client_id": "client"}'
PASTED = "https://sso.garmin.com/sso/embed?ticket=ST-0123456-abcDEF-sso"


class FakeClient:
    def __init__(self, owner: FakeGarmin) -> None:
        self.owner = owner
        self.tokens = ""

    def _exchange_service_ticket(self, ticket: str, service_url: str) -> None:
        self.owner.calls.append(("exchange", ticket, service_url))
        if self.owner.exchange_error:
            raise self.owner.exchange_error
        self.tokens = TOKENS

    def dumps(self) -> str:
        return self.tokens


class FakeGarmin:
    """Stands in for garminconnect.Garmin and records how it is used."""

    calls: ClassVar[list[tuple[Any, ...]]] = []
    exchange_error: ClassVar[Exception | None] = None
    login_error: ClassVar[Exception | None] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("init", args, kwargs))
        self.client = FakeClient(self)

    def login(self, tokenstore: str | None = None) -> None:
        self.calls.append(("login", tokenstore))
        if self.login_error:
            raise self.login_error
        self.client.tokens = tokenstore or ""

    def get_sleep_data(self, day: str) -> dict[str, str]:
        return {"day": day}

    def delete_activity(self, activity_id: str) -> None:
        raise AssertionError("a write method must never be reachable")


@pytest.fixture(autouse=True)
def fake_library(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FakeGarmin, "calls", [])
    monkeypatch.setattr(FakeGarmin, "exchange_error", None)
    monkeypatch.setattr(FakeGarmin, "login_error", None)
    monkeypatch.setattr(garmin, "Garmin", FakeGarmin)


def test_sign_in_url_sends_the_ticket_back_to_garmin_itself() -> None:
    url = urlparse(SIGN_IN_URL)
    query = parse_qs(url.query)

    assert (url.scheme, url.netloc, url.path) == ("https", "sso.garmin.com", "/sso/signin")
    assert query["service"] == [SSO_EMBED]
    assert query["embedWidget"] == ["true"]


@pytest.mark.parametrize(
    "pasted",
    [PASTED, "ST-0123456-abcDEF-sso", f"  {PASTED}&foo=bar\n", "ticket=ST-0123456-abcDEF-sso"],
)
def test_ticket_is_found_in_what_the_user_pastes(pasted: str) -> None:
    assert extract_ticket(pasted) == "ST-0123456-abcDEF-sso"


def test_pasting_something_without_a_ticket_is_an_error() -> None:
    with pytest.raises(LinkError, match="no ticket found"):
        extract_ticket("https://connect.garmin.com/modern/")


def test_linking_exchanges_the_ticket_and_never_uses_credentials() -> None:
    session = GarminSession.from_ticket(PASTED)

    assert session.tokens() == TOKENS
    assert ("exchange", "ST-0123456-abcDEF-sso", SSO_EMBED) in FakeGarmin.calls
    # No email or password is ever handed to the library.
    assert [call for call in FakeGarmin.calls if call[0] == "init"] == [
        ("init", (), {}),
        ("init", (), {}),
    ]


@pytest.mark.parametrize(
    "error",
    [GarminConnectAuthenticationError("expired"), GarminConnectConnectionError("down")],
)
def test_refused_ticket_is_a_link_error(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    monkeypatch.setattr(FakeGarmin, "exchange_error", error)

    with pytest.raises(LinkError, match="refused the ticket"):
        GarminSession.from_ticket(PASTED)


def test_session_resumes_from_stored_tokens() -> None:
    session = GarminSession.from_tokens(TOKENS)

    assert ("login", TOKENS) in FakeGarmin.calls
    assert session.tokens() == TOKENS


def test_rejected_tokens_require_a_new_link(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FakeGarmin, "login_error", GarminConnectAuthenticationError("rejected"))

    with pytest.raises(RelinkRequired, match="rejected"):
        GarminSession.from_tokens(TOKENS)


def test_connection_problems_are_not_mistaken_for_rejected_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(FakeGarmin, "login_error", GarminConnectConnectionError("timeout"))

    with pytest.raises(GarminConnectConnectionError):
        GarminSession.from_tokens(TOKENS)


def test_read_methods_can_be_called() -> None:
    session = GarminSession.from_tokens(TOKENS)

    assert session.call("get_sleep_data", "2026-01-15") == {"day": "2026-01-15"}


@pytest.mark.parametrize("method", ["delete_activity", "set_activity_name", "login", "client"])
def test_only_read_methods_can_be_called(method: str) -> None:
    session = GarminSession.from_tokens(TOKENS)

    with pytest.raises(ValueError, match="not a read method"):
        session.call(method, "1")


def test_tokens_rejected_during_a_call_require_a_new_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = GarminSession.from_tokens(TOKENS)

    def rejected(self: FakeGarmin, day: str) -> None:
        raise GarminConnectAuthenticationError("401")

    monkeypatch.setattr(FakeGarmin, "get_sleep_data", rejected)

    with pytest.raises(RelinkRequired):
        session.call("get_sleep_data", "2026-01-15")
