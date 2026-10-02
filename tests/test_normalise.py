import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from garmin_analyzer.db import make_session_factory
from garmin_analyzer.models import DailySummary, HeartRateSample, SleepSession, User
from garmin_analyzer.normalise import (
    daily_summary_rows,
    heart_rate_rows,
    normalise,
    sleep_session_rows,
)

FIXTURES = Path(__file__).parent / "fixtures" / "garmin"


def fixture(name: str) -> Any:
    """A synthetic Garmin response made by scripts/scrub_fixture.py."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def session(db: Engine) -> Iterator[Session]:
    with make_session_factory(db)() as session:
        yield session


def make_user(session: Session, email: str = "runner@example.com") -> User:
    user = User(email=email, password_hash="not-a-real-hash")  # noqa: S106
    session.add(user)
    session.commit()
    return user


def test_daily_summary_is_parsed() -> None:
    (row,) = daily_summary_rows(fixture("user_summary"))

    assert row["calendar_date"] == date(2026, 1, 13)
    assert row["steps"] == 6518
    assert row["distance_m"] == 8601
    assert row["floors_ascended"] == 8.36
    assert row["active_kcal"] == 924.67
    assert row["resting_hr"] == 53
    assert row["avg_stress"] == 20
    assert row["body_battery_high"] == 102
    # This account has no pulse-ox readings; Garmin sends null.
    assert row["avg_spo2"] is None


def test_sleep_session_is_parsed() -> None:
    (row,) = sleep_session_rows(fixture("sleep_data"))

    assert row["calendar_date"] == date(2026, 1, 15)
    assert row["start_at"] == datetime(2026, 1, 14, 22, 17, tzinfo=UTC)
    assert row["end_at"] == datetime(2026, 1, 15, 7, 0, tzinfo=UTC)
    assert row["sleep_s"] == 37645
    assert row["deep_s"] == 2692
    assert row["rem_s"] == 4925
    assert row["score"] == 95
    assert row["score_qualifier"] == "FAIR"
    assert row["avg_hrv"] == 39.24
    assert row["hrv_status"] == "BALANCED"


def test_heart_rate_samples_are_parsed() -> None:
    rows = heart_rate_rows(fixture("heart_rates"))

    assert len(rows) == 5
    assert rows[0] == {"measured_at": datetime(2026, 1, 13, 23, 24, tzinfo=UTC), "bpm": 39}


def test_heart_rate_gaps_are_skipped() -> None:
    payload = {"heartRateValues": [[1768346640000, 61], [1768346760000, None]]}

    assert [row["bpm"] for row in heart_rate_rows(payload)] == [61]


@pytest.mark.parametrize(
    "payload",
    [None, {}, [], {"heartRateValues": None}, {"dailySleepDTO": None}],
)
def test_empty_responses_produce_no_rows(payload: Any) -> None:
    assert daily_summary_rows(payload) == []
    assert sleep_session_rows(payload) == []
    assert heart_rate_rows(payload) == []


def test_night_without_recorded_sleep_produces_no_row() -> None:
    payload = fixture("sleep_data")
    payload["dailySleepDTO"]["sleepStartTimestampGMT"] = None

    assert sleep_session_rows(payload) == []


def test_missing_fields_become_null() -> None:
    (row,) = daily_summary_rows({"calendarDate": "2026-01-13", "totalSteps": 10})

    assert row["steps"] == 10
    assert row["resting_hr"] is None


def test_normalise_stores_rows_for_the_user(session: Session) -> None:
    user = make_user(session)

    assert normalise(session, user.id, "user_summary", fixture("user_summary")) == 1
    assert normalise(session, user.id, "sleep_data", fixture("sleep_data")) == 1
    assert normalise(session, user.id, "heart_rates", fixture("heart_rates")) == 5
    session.commit()

    summary = session.scalars(select(DailySummary)).one()
    assert (summary.user_id, summary.calendar_date, summary.steps) == (
        user.id,
        date(2026, 1, 13),
        6518,
    )
    assert session.scalars(select(SleepSession)).one().score == 95
    assert session.scalar(select(func.count()).select_from(HeartRateSample)) == 5


def test_normalise_again_updates_instead_of_duplicating(session: Session) -> None:
    user = make_user(session)
    payload = fixture("user_summary")
    normalise(session, user.id, "user_summary", payload)

    # The same day fetched later, after more steps were synced.
    payload["totalSteps"] = 9000
    normalise(session, user.id, "user_summary", payload)
    session.commit()

    assert session.scalars(select(DailySummary.steps)).all() == [9000]


def test_users_do_not_overwrite_each_other(session: Session) -> None:
    first = make_user(session)
    second = make_user(session, "cyclist@example.com")
    payload = fixture("user_summary")
    normalise(session, first.id, "user_summary", payload)
    payload["totalSteps"] = 1
    normalise(session, second.id, "user_summary", payload)
    session.commit()

    steps = dict(session.execute(select(DailySummary.user_id, DailySummary.steps)).all())
    assert steps == {first.id: 6518, second.id: 1}


def test_endpoints_without_a_parser_are_ignored(session: Session) -> None:
    user = make_user(session)

    assert normalise(session, user.id, "devices", [{"deviceId": 1}]) == 0


def test_empty_payload_stores_nothing(session: Session) -> None:
    user = make_user(session)

    assert normalise(session, user.id, "heart_rates", {}) == 0
