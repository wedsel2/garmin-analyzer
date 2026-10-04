"""Tests for the scheduled worker. No sync is run: the worker is given a fake one."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from garmin_analyzer.db import make_engine
from garmin_analyzer.models import GarminLink, LinkStatus, User
from garmin_analyzer.users import add_user
from garmin_analyzer.worker import REQUEST_GAP, TICK_SECONDS, due_users, run_due, run_forever

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


def add_linked(
    db: Engine,
    email: str,
    synced_ago: timedelta | None,
    status: LinkStatus = LinkStatus.ACTIVE,
    requested: bool = False,
) -> uuid.UUID:
    with Session(db) as session:
        user = add_user(session, email)
        session.flush()
        session.add(
            GarminLink(
                user_id=user.id,
                encrypted_tokens=b"x",
                status=status,
                last_synced_at=None if synced_ago is None else NOW - synced_ago,
                sync_requested_at=NOW if requested else None,
                sync_requested_days=14 if requested else None,
            )
        )
        session.commit()
        return user.id


def due(db: Engine, attempted: dict[uuid.UUID, datetime] | None = None) -> list[str]:
    with Session(db) as session:
        return [user.email for user in due_users(session, NOW, HOUR, attempted or {})]


class Syncs:
    """A fake sync that records who was synced."""

    def __init__(self, fails_for: str | None = None) -> None:
        self.emails: list[str] = []
        self.days: list[int | None] = []
        self.fails_for = fails_for

    def __call__(self, session: Session, user: User, days: int | None) -> None:
        self.emails.append(user.email)
        self.days.append(days)
        if user.email == self.fails_for:
            raise RuntimeError("sync broke")


def test_users_are_due_when_their_last_sync_is_older_than_the_interval(db: Engine) -> None:
    add_linked(db, "recent@example.com", timedelta(minutes=59))
    add_linked(db, "old@example.com", timedelta(hours=1))
    add_linked(db, "older@example.com", timedelta(days=2))
    add_linked(db, "new@example.com", None)
    add_linked(db, "relink@example.com", timedelta(days=2), LinkStatus.NEEDS_RELINK)
    with Session(db) as session:
        add_user(session, "unlinked@example.com")
        session.commit()

    # Never synced first, then the longest ago.
    assert due(db) == ["new@example.com", "older@example.com", "old@example.com"]


def test_a_user_tried_within_the_interval_is_not_due_again(db: Engine) -> None:
    failing = add_linked(db, "failing@example.com", timedelta(days=2))

    assert due(db, {failing: NOW - timedelta(minutes=59)}) == []
    assert due(db, {failing: NOW - HOUR}) == ["failing@example.com"]


def test_a_user_who_asked_for_a_sync_does_not_wait_for_the_interval(db: Engine) -> None:
    add_linked(db, "asked@example.com", timedelta(minutes=20), requested=True)
    add_linked(db, "just-synced@example.com", timedelta(minutes=4), requested=True)
    add_linked(db, "relink@example.com", timedelta(days=2), LinkStatus.NEEDS_RELINK, requested=True)
    tried = add_linked(db, "tried@example.com", timedelta(minutes=20), requested=True)

    assert due(db, {tried: NOW - timedelta(minutes=4)}) == ["asked@example.com"]
    assert due(db, {tried: NOW - REQUEST_GAP}) == ["asked@example.com", "tried@example.com"]


def test_a_request_never_waits_longer_than_the_interval(db: Engine) -> None:
    add_linked(db, "asked@example.com", timedelta(minutes=2), requested=True)

    with Session(db) as session:
        users = due_users(session, NOW, timedelta(minutes=1), {})

    assert [user.email for user in users] == ["asked@example.com"]


def test_a_request_is_spent_when_its_sync_starts(db: Engine) -> None:
    asked = add_linked(db, "asked@example.com", timedelta(minutes=20), requested=True)
    syncs = Syncs(fails_for="asked@example.com")
    attempted: dict[uuid.UUID, datetime] = {}

    with pytest.raises(RuntimeError):
        run_due(db, syncs, HOUR, attempted, NOW)

    assert syncs.days == [14]
    with Session(db) as session:
        link = session.get_one(GarminLink, asked)
        assert (link.sync_requested_at, link.sync_requested_days) == (None, None)
    assert run_due(db, syncs, HOUR, attempted, NOW + REQUEST_GAP) == 0


def test_run_due_syncs_each_due_user_once_and_remembers_the_attempt(db: Engine) -> None:
    add_linked(db, "a@example.com", None)
    add_linked(db, "b@example.com", timedelta(hours=3))
    add_linked(db, "recent@example.com", timedelta(minutes=5))
    syncs = Syncs()
    attempted: dict[uuid.UUID, datetime] = {}

    assert run_due(db, syncs, HOUR, attempted, NOW) == 2
    # The fake does not record a sync time, as a failed sync would not.
    assert run_due(db, syncs, HOUR, attempted, NOW + timedelta(minutes=30)) == 0
    assert run_due(db, syncs, HOUR, attempted, NOW + HOUR) == 3

    assert syncs.emails == [
        "a@example.com",
        "b@example.com",
        "a@example.com",
        "b@example.com",
        "recent@example.com",
    ]


def test_an_attempt_is_remembered_when_the_sync_breaks(db: Engine) -> None:
    broken = add_linked(db, "broken@example.com", None)
    attempted: dict[uuid.UUID, datetime] = {}

    with pytest.raises(RuntimeError):
        run_due(db, Syncs(fails_for="broken@example.com"), HOUR, attempted, NOW)

    assert attempted == {broken: NOW}


class Stop(Exception):
    """Ends the endless loop of the worker in a test."""


def test_the_worker_looks_every_minute_until_it_is_stopped(db: Engine) -> None:
    add_linked(db, "a@example.com", None)
    syncs = Syncs()
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 3:
            raise Stop

    with pytest.raises(Stop):
        run_forever(db, syncs, HOUR, sleep)

    assert slept == [TICK_SECONDS] * 3
    # Synced in the first round; not due again within the hour.
    assert syncs.emails == ["a@example.com"]


def test_the_worker_survives_a_database_that_is_down(capsys: pytest.CaptureFixture[str]) -> None:
    unreachable = make_engine("postgresql+psycopg://nobody@127.0.0.1:1/none")
    rounds: list[float] = []

    def sleep(seconds: float) -> None:
        rounds.append(seconds)
        if len(rounds) == 2:
            raise Stop

    with pytest.raises(Stop):
        run_forever(unreachable, Syncs(), HOUR, sleep)

    assert len(rounds) == 2
    assert capsys.readouterr().err.count("database error, trying again in a minute") == 2


def test_database_errors_do_not_show_statement_values(db: Engine) -> None:
    statement = text("SELECT :value FROM a_table_that_does_not_exist")

    with Session(db) as session, pytest.raises(ProgrammingError) as error:
        session.execute(statement, {"value": "a heart rate"})

    assert "a_table_that_does_not_exist" in str(error.value)
    assert "a heart rate" not in str(error.value)
