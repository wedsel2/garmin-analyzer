"""Tests for the user, link and collect commands. Garmin is replaced by a fake."""

from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from garmin_analyzer import cli
from garmin_analyzer.collector import SyncResult
from garmin_analyzer.db import make_session_factory
from garmin_analyzer.garmin import GarminSession, LinkError, RelinkRequired
from garmin_analyzer.links import AlreadySyncing
from garmin_analyzer.models import GarminLink, LinkStatus, User
from garmin_analyzer.tokens import TokenCipher, generate_key

PASTED = "https://sso.garmin.com/sso/embed?ticket=ST-0123456-abcDEF-sso"


class StubGarmin(GarminSession):
    def __init__(self) -> None:
        pass

    def tokens(self) -> str:
        return "linked-tokens"


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = generate_key()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", key)
    return key


def users(db: Engine) -> list[tuple[str, bool]]:
    with Session(db) as session:
        rows = session.execute(select(User.email, User.is_admin).order_by(User.created_at))
        return [(email, is_admin) for email, is_admin in rows]


def link_status(db: Engine, email: str) -> LinkStatus | None:
    with Session(db) as session:
        return session.scalar(
            select(GarminLink.status)
            .join(User, User.id == GarminLink.user_id)
            .where(User.email == email)
        )


def test_first_user_becomes_administrator(db: Engine, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["user-add", "  Runner@Example.com "]) == 0
    assert cli.main(["user-add", "cyclist@example.com"]) == 0

    assert users(db) == [("runner@example.com", True), ("cyclist@example.com", False)]
    assert capsys.readouterr().out == (
        "created administrator runner@example.com\ncreated user cyclist@example.com\n"
    )


@pytest.mark.parametrize(
    ("email", "message"),
    [("runner@example.com", "already exists"), ("not-an-address", "is not an email address")],
)
def test_user_add_rejects_duplicates_and_non_addresses(
    db: Engine, capsys: pytest.CaptureFixture[str], email: str, message: str
) -> None:
    cli.main(["user-add", "runner@example.com"])

    assert cli.main(["user-add", email]) == 1
    assert message in capsys.readouterr().err
    assert len(users(db)) == 1


def test_link_stores_tokens_from_the_pasted_address(
    db: Engine, key: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["user-add", "runner@example.com"])
    pasted: list[str] = []

    def from_ticket(text: str) -> GarminSession:
        pasted.append(text)
        return StubGarmin()

    monkeypatch.setattr(GarminSession, "from_ticket", from_ticket)
    monkeypatch.setattr("builtins.input", lambda prompt: PASTED)

    assert cli.main(["link", "runner@example.com"]) == 0

    assert pasted == [PASTED]
    output = capsys.readouterr().out
    assert "https://sso.garmin.com/sso/signin?" in output
    assert "linked Garmin for runner@example.com" in output
    with Session(db) as session:
        stored = session.scalars(select(GarminLink.encrypted_tokens)).one()
    assert TokenCipher(key).decrypt(stored) == "linked-tokens"


def test_link_reports_a_refused_ticket(
    db: Engine, key: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["user-add", "runner@example.com"])

    def refused(text: str) -> GarminSession:
        raise LinkError("Garmin refused the ticket")

    monkeypatch.setattr(GarminSession, "from_ticket", refused)
    monkeypatch.setattr("builtins.input", lambda prompt: PASTED)

    assert cli.main(["link", "runner@example.com"]) == 1
    assert "Garmin refused the ticket" in capsys.readouterr().err
    assert link_status(db, "runner@example.com") is None


def test_link_needs_an_existing_user(
    db: Engine, key: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["link", "nobody@example.com"]) == 1
    assert "no user with email nobody@example.com" in capsys.readouterr().err


def test_link_and_collect_need_the_encryption_key(
    db: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)

    assert cli.main(["link", "runner@example.com"]) == 2
    assert cli.main(["collect"]) == 2
    assert capsys.readouterr().err.count("TOKEN_ENCRYPTION_KEY is not set") == 2


# collect: which users, which days, and how results are reported.


@pytest.fixture
def linked_users(db: Engine, key: str) -> None:
    """Two users with an active link and one whose link needs a new sign-in."""
    cipher = TokenCipher(key)
    with make_session_factory(db)() as session:
        for email, status in (
            ("runner@example.com", LinkStatus.ACTIVE),
            ("cyclist@example.com", LinkStatus.ACTIVE),
            ("swimmer@example.com", LinkStatus.NEEDS_RELINK),
        ):
            user = User(email=email, password_hash="!")  # noqa: S106
            session.add(user)
            session.flush()
            session.add(
                GarminLink(user_id=user.id, encrypted_tokens=cipher.encrypt("t"), status=status)
            )
        session.commit()


@pytest.fixture
def collected(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace the collector and record what the command asks of it."""
    runs: list[dict[str, Any]] = []

    def fake_collect_user(
        session: Session, user_id: Any, cipher: TokenCipher, since: date, today: date, pause: float
    ) -> SyncResult:
        email = session.get_one(User, user_id).email
        runs.append({"email": email, "since": since, "today": today, "pause": pause})
        # A catch-up covered more than was asked for.
        return SyncResult(calls=20, rows=7, since=date(2020, 5, 17))

    monkeypatch.setattr(cli, "collect_user", fake_collect_user)
    return runs


def test_collect_without_an_email_syncs_every_active_link(
    linked_users: None, collected: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["collect"]) == 0

    assert [run["email"] for run in collected] == ["cyclist@example.com", "runner@example.com"]
    today = date.today()
    assert all((today - run["since"]).days == 2 and run["today"] == today for run in collected)
    assert f"runner@example.com: 2020-05-17 to {today}, 20 requests" in capsys.readouterr().out


def test_collect_options_select_user_days_and_pace(
    linked_users: None, collected: list[dict[str, Any]]
) -> None:
    assert cli.main(["collect", "runner@example.com", "--days", "10", "--pause", "0.5"]) == 0
    assert cli.main(["collect", "runner@example.com", "--since", "2026-01-01"]) == 0

    assert [run["email"] for run in collected] == ["runner@example.com"] * 2
    assert (date.today() - collected[0]["since"]).days == 9
    assert collected[0]["pause"] == 0.5
    assert collected[1]["since"] == date(2026, 1, 1)


def test_collect_reports_failed_requests_and_an_early_stop(
    linked_users: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def partly(*args: Any) -> SyncResult:
        return SyncResult(
            calls=5, rows=1, errors=["sleep_data 2026-01-15: 503"], stopped="rate limit reached"
        )

    monkeypatch.setattr(cli, "collect_user", partly)

    assert cli.main(["collect", "runner@example.com"]) == 1
    captured = capsys.readouterr()
    assert "5 requests, 1 rows, 1 failed requests" in captured.out
    assert "failed: sleep_data 2026-01-15: 503" in captured.err
    assert "stopped early: rate limit reached" in captured.err


def test_collect_continues_with_other_users_when_one_cannot_be_opened(
    linked_users: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def one_rejected(session: Session, user_id: Any, *args: Any) -> SyncResult:
        if session.get_one(User, user_id).email == "cyclist@example.com":
            raise RelinkRequired("tokens rejected")
        return SyncResult(calls=3)

    monkeypatch.setattr(cli, "collect_user", one_rejected)

    assert cli.main(["collect"]) == 1
    captured = capsys.readouterr()
    assert "cyclist@example.com: tokens rejected" in captured.err
    assert "runner@example.com" in captured.out


def test_collect_continues_with_other_users_after_an_unexpected_failure(
    linked_users: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def one_broken(session: Session, user_id: Any, *args: Any) -> SyncResult:
        if session.get_one(User, user_id).email == "cyclist@example.com":
            raise ValueError("a response nobody foresaw")
        return SyncResult(calls=3)

    monkeypatch.setattr(cli, "collect_user", one_broken)

    assert cli.main(["collect"]) == 1
    captured = capsys.readouterr()
    assert "cyclist@example.com: ValueError: a response nobody foresaw" in captured.err
    assert "Traceback" in captured.err
    assert "runner@example.com" in captured.out


def test_collect_skips_a_user_who_is_already_being_synced(
    linked_users: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def busy(session: Session, user_id: Any, *args: Any) -> SyncResult:
        if session.get_one(User, user_id).email == "cyclist@example.com":
            raise AlreadySyncing("a backfill is running")
        return SyncResult(calls=3)

    monkeypatch.setattr(cli, "collect_user", busy)

    # Not a failure: the other sync is doing the work.
    assert cli.main(["collect"]) == 0
    captured = capsys.readouterr()
    assert "cyclist@example.com: skipped, another sync is running" in captured.err
    assert "runner@example.com" in captured.out


@pytest.mark.parametrize(
    "arguments", [["--days", "0"], ["--days", "-3"], ["--pause", "-1"], ["--days", "many"]]
)
def test_collect_rejects_values_that_make_no_sense(
    linked_users: None, collected: list[dict[str, Any]], arguments: list[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["collect", *arguments])

    assert exit_info.value.code == 2
    assert collected == []


def test_collect_rejects_a_start_in_the_future(
    linked_users: None, collected: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["collect", "--since", "2999-01-01"]) == 1
    assert "is in the future" in capsys.readouterr().err
    assert collected == []


def test_collect_reports_tokens_that_cannot_be_decrypted(
    linked_users: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The key was replaced after the links were stored.
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())

    assert cli.main(["collect", "runner@example.com"]) == 1
    assert "stored Garmin tokens cannot be decrypted" in capsys.readouterr().err
