"""Tests for the collector, against a fake Garmin session. No test contacts Garmin."""

import json
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from garmin_analyzer.collector import (
    ACCOUNT_ENDPOINTS,
    ACTIVITY_ENDPOINTS,
    CATCH_UP_INTERVAL,
    DAILY_ENDPOINTS,
    Collector,
    collect_user,
)
from garmin_analyzer.db import make_session_factory
from garmin_analyzer.garmin import GarminError, GarminSession, RateLimited, RelinkRequired
from garmin_analyzer.links import AlreadySyncing, NotLinked, store_link, sync_lock
from garmin_analyzer.models import (
    Activity,
    ActivityZone,
    DailySummary,
    GarminLink,
    LinkStatus,
    RawFile,
    RawPayload,
    User,
)
from garmin_analyzer.tokens import TokenCipher, generate_key

FIXTURES = Path(__file__).parent / "fixtures" / "garmin"
TODAY = date(2026, 1, 15)


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class FakeGarmin(GarminSession):
    """Answers like Garmin would, from fixtures, and records every request."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.failures: dict[str, Exception] = {}
        self.activities: list[dict[str, Any]] = [fixture("activities")[0]]
        self.current_tokens = "tokens-after-sync"

    def tokens(self) -> str:
        return self.current_tokens

    def account_id(self) -> int | None:
        return 1234

    def call(self, method: str, *args: Any) -> Any:
        self.calls.append((method, *args))
        if method in self.failures:
            raise self.failures[method]
        if method == "get_user_summary":
            return fixture("user_summary") | {"calendarDate": args[0]}
        if method == "get_activities_by_date":
            return self.activities
        if method == "get_activity_hr_in_timezones":
            return fixture("activity_hr_in_timezones")
        if method == "get_hrv_data":
            # Garmin answers with nothing at all for a night without HRV.
            return None
        return {}

    def download_original(self, activity_id: str) -> bytes:
        self.calls.append(("download_original", activity_id))
        return b"PK archive of " + activity_id.encode()

    def count(self, method: str) -> int:
        return sum(1 for call in self.calls if call[0] == method)


@pytest.fixture
def session(db: Engine) -> Iterator[Session]:
    with make_session_factory(db)() as session:
        yield session


@pytest.fixture
def user(session: Session) -> User:
    user = User(email="runner@example.com", password_hash="!")  # noqa: S106
    session.add(user)
    session.commit()
    return user


@pytest.fixture
def garmin() -> FakeGarmin:
    return FakeGarmin()


def collector(session: Session, user: User, garmin: FakeGarmin) -> Collector:
    return Collector(session, user.id, garmin, pause=0.25, sleep=lambda seconds: None)


def raw_count(session: Session, endpoint: str) -> int:
    count = session.scalar(
        select(func.count()).select_from(RawPayload).where(RawPayload.endpoint == endpoint)
    )
    return count or 0


def test_sync_stores_raw_and_normalised_data(
    session: Session, user: User, garmin: FakeGarmin
) -> None:
    result = collector(session, user, garmin).sync(since=date(2026, 1, 13), today=TODAY)

    assert result.errors == []
    assert result.stopped is None
    # Account-wide data once, every daily endpoint for each of the three days.
    for endpoint in ACCOUNT_ENDPOINTS:
        assert raw_count(session, endpoint) == 1
    for endpoint in DAILY_ENDPOINTS:
        assert raw_count(session, endpoint) == 3
    days = session.scalars(select(DailySummary.calendar_date).order_by("calendar_date")).all()
    assert days == [date(2026, 1, 13), date(2026, 1, 14), date(2026, 1, 15)]
    assert result.rows > 0


def test_empty_answers_are_stored_so_they_are_not_asked_again(
    session: Session, user: User, garmin: FakeGarmin
) -> None:
    collector(session, user, garmin).sync(since=TODAY, today=TODAY)

    stored = session.scalars(select(RawPayload).where(RawPayload.endpoint == "hrv_data")).one()
    assert stored.payload is None
    assert stored.calendar_date == TODAY


def test_activity_is_stored_in_full(session: Session, user: User, garmin: FakeGarmin) -> None:
    collector(session, user, garmin).sync(since=TODAY, today=TODAY)

    assert session.scalars(select(Activity.activity_id)).all() == [1]
    for endpoint in ("activity_summary", *ACTIVITY_ENDPOINTS):
        assert raw_count(session, endpoint) == 1
    # Zones do not name their activity; it comes from the key they are stored under.
    assert set(session.scalars(select(ActivityZone.activity_id))) == {1}
    original = session.scalars(select(RawFile)).one()
    assert (original.kind, original.resource_key) == ("activity_original", "1")
    assert original.content == b"PK archive of 1"


def test_second_sync_refetches_recent_days_only(
    session: Session, user: User, garmin: FakeGarmin
) -> None:
    since = date(2026, 1, 10)
    collector(session, user, garmin).sync(since, TODAY)
    garmin.calls.clear()

    collector(session, user, garmin).sync(since, TODAY)

    # Today and yesterday can still change; the four older days are complete.
    assert garmin.count("get_user_summary") == 2
    assert {call[1] for call in garmin.calls if call[0] == "get_user_summary"} == {
        "2026-01-15",
        "2026-01-14",
    }
    # Activity details and the original file are fetched once.
    assert garmin.count("get_activity_details") == 0
    assert garmin.count("download_original") == 0
    assert raw_count(session, "user_summary") == 6
    assert session.scalar(select(func.count()).select_from(RawFile)) == 1


def test_refetched_day_replaces_the_stored_answer(
    session: Session, user: User, garmin: FakeGarmin
) -> None:
    collector(session, user, garmin).sync(TODAY, TODAY)
    before = session.scalars(select(DailySummary.steps)).one()
    assert before is not None

    def more_steps(method: str, *args: Any) -> Any:
        if method == "get_user_summary":
            return fixture("user_summary") | {"calendarDate": args[0], "totalSteps": before + 500}
        return FakeGarmin.call(garmin, method, *args)

    garmin.call = more_steps  # type: ignore[method-assign]
    collector(session, user, garmin).sync(TODAY, TODAY)
    session.expire_all()

    assert session.scalars(select(DailySummary.steps)).all() == [before + 500]
    assert raw_count(session, "user_summary") == 1


def test_failed_request_is_recorded_and_retried_next_time(
    session: Session, user: User, garmin: FakeGarmin
) -> None:
    since = date(2026, 1, 10)
    garmin.failures["get_sleep_data"] = GarminError("503 from Garmin")

    result = collector(session, user, garmin).sync(since, TODAY)

    assert len(result.errors) == 6
    assert result.errors[0] == "sleep_data 2026-01-15: 503 from Garmin"
    assert raw_count(session, "sleep_data") == 0
    # Everything else was still collected.
    assert raw_count(session, "user_summary") == 6

    garmin.failures.clear()
    garmin.calls.clear()
    collector(session, user, garmin).sync(since, TODAY)

    assert garmin.count("get_sleep_data") == 6
    assert raw_count(session, "sleep_data") == 6


def test_requests_are_paced(session: Session, user: User, garmin: FakeGarmin) -> None:
    pauses: list[float] = []
    paced = Collector(session, user.id, garmin, pause=0.25, sleep=pauses.append)

    result = paced.sync(TODAY, TODAY)

    assert pauses == [0.25] * result.calls
    assert result.calls == len(garmin.calls)


def test_activity_without_an_id_is_skipped(
    session: Session, user: User, garmin: FakeGarmin
) -> None:
    garmin.activities = [{"activityName": "broken entry"}]

    result = collector(session, user, garmin).sync(TODAY, TODAY)

    assert result.errors == []
    assert raw_count(session, "activity_summary") == 0


def test_failed_file_download_is_retried_next_time(
    session: Session, user: User, garmin: FakeGarmin, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(activity_id: str) -> bytes:
        raise GarminError("download failed")

    monkeypatch.setattr(garmin, "download_original", unavailable)
    result = collector(session, user, garmin).sync(TODAY, TODAY)

    assert result.errors == ["activity_original 1: download failed"]
    assert session.scalar(select(func.count()).select_from(RawFile)) == 0

    monkeypatch.undo()
    collector(session, user, garmin).sync(TODAY, TODAY)

    assert session.scalar(select(func.count()).select_from(RawFile)) == 1


@pytest.mark.parametrize("error", [RateLimited("429"), RelinkRequired("401")])
def test_file_download_does_not_swallow_a_stop_signal(
    session: Session,
    user: User,
    garmin: FakeGarmin,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    def stop(activity_id: str) -> bytes:
        raise error

    monkeypatch.setattr(garmin, "download_original", stop)

    with pytest.raises(type(error)):
        collector(session, user, garmin).sync(TODAY, TODAY)


def test_answer_that_cannot_be_normalised_is_kept_and_the_sync_continues(
    session: Session, user: User, garmin: FakeGarmin
) -> None:
    def odd_steps(method: str, *args: Any) -> Any:
        if method == "get_steps_data":
            # An interval without its start time, which the parser requires.
            return [{"endGMT": "2026-01-15T00:15:00.0", "steps": 5}]
        return FakeGarmin.call(garmin, method, *args)

    garmin.call = odd_steps  # type: ignore[method-assign]

    result = collector(session, user, garmin).sync(TODAY, TODAY)

    assert result.errors == [
        "steps_data 2026-01-15: stored but not normalised: KeyError: 'startGMT'"
    ]
    assert raw_count(session, "steps_data") == 1
    # Endpoints after the failing one were still collected and normalised.
    assert raw_count(session, "training_status") == 1
    assert session.scalars(select(Activity.activity_id)).all() == [1]


# collect_user: opening the link, stopping early, keeping tokens.


@pytest.fixture
def cipher() -> TokenCipher:
    return TokenCipher(generate_key())


@pytest.fixture
def linked(
    session: Session,
    user: User,
    cipher: TokenCipher,
    garmin: FakeGarmin,
    monkeypatch: pytest.MonkeyPatch,
) -> FakeGarmin:
    """The user has a stored link, and opening it yields the fake session."""
    garmin.current_tokens = "tokens-at-link"
    store_link(session, user.id, cipher, garmin)
    session.commit()
    garmin.current_tokens = "tokens-after-sync"
    monkeypatch.setattr(GarminSession, "from_tokens", lambda tokens: garmin)
    return garmin


def link_of(session: Session, user: User) -> GarminLink:
    session.expire_all()
    return session.get_one(GarminLink, user.id)


def run(session: Session, user: User, cipher: TokenCipher) -> Any:
    return collect_user(
        session, user.id, cipher, since=TODAY, today=TODAY, pause=0, sleep=lambda seconds: None
    )


def test_collect_user_syncs_and_records_it(
    session: Session, user: User, cipher: TokenCipher, linked: FakeGarmin
) -> None:
    result = run(session, user, cipher)
    session.expire_all()

    assert result.stopped is None
    link = session.get_one(GarminLink, user.id)
    assert link.last_synced_at is not None
    assert link.status is LinkStatus.ACTIVE
    # A refresh during the sync may have replaced the tokens; the new ones are kept.
    assert cipher.decrypt(link.encrypted_tokens) == "tokens-after-sync"
    # The first sync of a link is also its first catch-up over two weeks.
    assert raw_count(session, "user_summary") == 14


def test_rate_limit_stops_the_sync_and_keeps_what_was_fetched(
    session: Session, user: User, cipher: TokenCipher, linked: FakeGarmin
) -> None:
    linked.failures["get_sleep_data"] = RateLimited("429")

    result = run(session, user, cipher)
    session.expire_all()

    assert result.stopped == "Garmin rate limit reached; try again later"
    # The daily summary comes before sleep and was already fetched.
    assert raw_count(session, "user_summary") == 1
    assert link_of(session, user).last_catch_up_at is None
    assert linked.count("get_heart_rates") == 0
    link = session.get_one(GarminLink, user.id)
    assert link.status is LinkStatus.ACTIVE
    assert link.last_synced_at is None


def test_rejected_tokens_during_a_sync_mark_the_link(
    session: Session, user: User, cipher: TokenCipher, linked: FakeGarmin
) -> None:
    linked.failures["get_sleep_data"] = RelinkRequired("401 from Garmin")

    result = run(session, user, cipher)
    session.expire_all()

    assert result.stopped == "Garmin rejected the tokens; link the account again"
    link = session.get_one(GarminLink, user.id)
    assert link.status is LinkStatus.NEEDS_RELINK
    assert link.last_error == "401 from Garmin"


def test_rejected_tokens_when_opening_the_link_are_recorded(
    session: Session,
    user: User,
    cipher: TokenCipher,
    linked: FakeGarmin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def rejected(tokens: str) -> GarminSession:
        raise RelinkRequired("refresh token expired")

    monkeypatch.setattr(GarminSession, "from_tokens", rejected)

    with pytest.raises(RelinkRequired):
        run(session, user, cipher)
    session.rollback()
    session.expire_all()

    assert session.get_one(GarminLink, user.id).status is LinkStatus.NEEDS_RELINK
    assert linked.calls == []


def test_user_without_a_link_cannot_be_collected(
    session: Session, user: User, cipher: TokenCipher
) -> None:
    with pytest.raises(NotLinked):
        run(session, user, cipher)


def test_tokens_are_saved_even_when_the_sync_fails_unexpectedly(
    session: Session,
    user: User,
    cipher: TokenCipher,
    linked: FakeGarmin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(self: Collector, since: date, today: date, refetch_days: int) -> Any:
        # The library refreshed the tokens, then something unforeseen happened.
        linked.current_tokens = "tokens-refreshed-mid-sync"
        raise RuntimeError("unforeseen")

    monkeypatch.setattr(Collector, "sync", broken)

    with pytest.raises(RuntimeError):
        run(session, user, cipher)
    session.expire_all()

    link = session.get_one(GarminLink, user.id)
    assert cipher.decrypt(link.encrypted_tokens) == "tokens-refreshed-mid-sync"
    assert link.last_synced_at is None


def test_refreshed_tokens_are_stored_during_the_sync_not_only_at_its_end(
    session: Session, user: User, cipher: TokenCipher, linked: FakeGarmin, db: Engine
) -> None:
    stored_midway: list[str] = []

    def refresh_then_look(method: str, *args: Any) -> Any:
        if method == "get_user_profile":
            # The library refreshes the tokens on the first request.
            linked.current_tokens = "tokens-refreshed-mid-sync"
        if method == "get_activities_by_date":
            # What a sync killed at this point would leave behind.
            with Session(db) as other:
                stored_midway.append(
                    cipher.decrypt(other.get_one(GarminLink, user.id).encrypted_tokens)
                )
        return FakeGarmin.call(linked, method, *args)

    linked.call = refresh_then_look  # type: ignore[method-assign]
    run(session, user, cipher)

    assert stored_midway == ["tokens-refreshed-mid-sync"]


def test_a_user_who_is_being_synced_is_not_synced_twice(
    session: Session, user: User, cipher: TokenCipher, linked: FakeGarmin, db: Engine
) -> None:
    with (
        make_session_factory(db)() as other,
        sync_lock(other, user.id),
        pytest.raises(AlreadySyncing),
    ):
        run(session, user, cipher)

    assert linked.calls == []


# Weekly catch-up: days that were stored empty get a second chance.


def summary_days(garmin: FakeGarmin) -> list[str]:
    return [call[1] for call in garmin.calls if call[0] == "get_user_summary"]


def test_first_sync_covers_the_last_two_weeks(
    session: Session, user: User, cipher: TokenCipher, linked: FakeGarmin
) -> None:
    result = run(session, user, cipher)
    session.expire_all()

    days = summary_days(linked)
    assert len(days) == 14
    assert (max(days), min(days)) == ("2026-01-15", "2026-01-02")
    # The result reports the period that was really covered, not the one asked for.
    assert result.since == date(2026, 1, 2)
    assert session.get_one(GarminLink, user.id).last_catch_up_at is not None


def test_sync_soon_after_a_catch_up_fetches_recent_days_only(
    session: Session, user: User, cipher: TokenCipher, linked: FakeGarmin
) -> None:
    run(session, user, cipher)
    linked.calls.clear()

    run(session, user, cipher)

    assert summary_days(linked) == ["2026-01-15"]


def test_a_sync_fetches_as_many_stored_days_again_as_it_is_asked_to(
    session: Session, user: User, cipher: TokenCipher, linked: FakeGarmin
) -> None:
    since = TODAY - timedelta(days=27)
    collect_user(session, user.id, cipher, since, TODAY, pause=0, sleep=lambda seconds: None)
    linked.calls.clear()

    collect_user(
        session, user.id, cipher, since, TODAY, pause=0, sleep=lambda seconds: None, refetch_days=28
    )

    assert len(summary_days(linked)) == 28


def test_catch_up_a_week_later_fetches_stored_days_again(
    session: Session, user: User, cipher: TokenCipher, linked: FakeGarmin
) -> None:
    run(session, user, cipher)
    link = session.get_one(GarminLink, user.id)
    assert link.last_catch_up_at is not None
    link.last_catch_up_at -= CATCH_UP_INTERVAL
    session.commit()
    linked.calls.clear()

    # The watch was away from the phone; this day was stored with no steps
    # and Garmin has the real figure now.
    def late_upload(method: str, *args: Any) -> Any:
        if method == "get_user_summary" and args[0] == "2026-01-08":
            linked.calls.append((method, *args))
            return fixture("user_summary") | {"calendarDate": args[0], "totalSteps": 4321}
        return FakeGarmin.call(linked, method, *args)

    linked.call = late_upload  # type: ignore[method-assign]
    run(session, user, cipher)
    session.expire_all()

    assert len(summary_days(linked)) == 14
    steps = session.scalar(
        select(DailySummary.steps).where(DailySummary.calendar_date == date(2026, 1, 8))
    )
    assert steps == 4321


def test_interrupted_catch_up_is_tried_again_next_time(
    session: Session, user: User, cipher: TokenCipher, linked: FakeGarmin
) -> None:
    linked.failures["get_sleep_data"] = RateLimited("429")
    run(session, user, cipher)
    session.expire_all()
    assert session.get_one(GarminLink, user.id).last_catch_up_at is None

    linked.failures.clear()
    linked.calls.clear()
    run(session, user, cipher)

    assert len(summary_days(linked)) == 14
