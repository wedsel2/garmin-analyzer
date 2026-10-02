import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from garmin_analyzer.db import make_session_factory
from garmin_analyzer.models import (
    BodyBatterySample,
    DailySummary,
    HeartRateSample,
    HrvReading,
    HrvSummary,
    RespirationSample,
    SleepSession,
    StepInterval,
    StressSample,
    User,
)
from garmin_analyzer.normalise import (
    body_battery_rows,
    daily_summary_rows,
    heart_rate_rows,
    hrv_reading_rows,
    hrv_summary_rows,
    normalise,
    respiration_rows,
    sleep_session_rows,
    step_interval_rows,
    stress_rows,
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


def test_stress_and_body_battery_come_from_one_response() -> None:
    payload = fixture("stress_data")

    stress = stress_rows(payload)
    battery = body_battery_rows(payload)

    assert len(stress) == len(battery) == 5
    assert stress[0] == {"measured_at": datetime(2026, 1, 13, 20, 42, tzinfo=UTC), "level": 48}
    assert battery[0] == {"measured_at": datetime(2026, 1, 13, 20, 42, tzinfo=UTC), "level": 8}


def test_unmeasured_points_are_skipped() -> None:
    # Garmin uses -1 and -2 for "not measured"; they must not be charted as readings.
    stress = fixture("stress_data")
    stress["stressValuesArray"] = [[1768336920000, -1], [1768337100000, -2], [1768337280000, 25]]
    respiration = fixture("respiration_data")
    respiration["respirationValuesArray"] = [[1768339440000, -2.0], [1768339560000, 14.0]]

    assert [row["level"] for row in stress_rows(stress)] == [25]
    assert [row["breaths_per_min"] for row in respiration_rows(respiration)] == [14.0]


def test_values_are_found_by_descriptor_not_position() -> None:
    payload = {
        "stressValueDescriptorsDTOList": [
            {"index": 1, "key": "timestamp"},
            {"index": 0, "key": "stressLevel"},
        ],
        "stressValuesArray": [[33, 1768336920000]],
    }

    assert stress_rows(payload) == [
        {"measured_at": datetime(2026, 1, 13, 20, 42, tzinfo=UTC), "level": 33}
    ]


def test_series_without_descriptors_produce_no_rows() -> None:
    assert stress_rows({"stressValuesArray": [[1768336920000, 25]]}) == []


def test_respiration_is_parsed() -> None:
    rows = respiration_rows(fixture("respiration_data"))

    assert rows[0] == {
        "measured_at": datetime(2026, 1, 13, 21, 24, tzinfo=UTC),
        "breaths_per_min": 15.5,
    }


def test_hrv_summary_and_readings_are_parsed() -> None:
    payload = fixture("hrv_data")

    (summary,) = hrv_summary_rows(payload)
    readings = hrv_reading_rows(payload)

    assert summary == {
        "calendar_date": date(2026, 1, 14),
        "weekly_avg": 38,
        "last_night_avg": 60,
        "last_night_5min_high": 102,
        "baseline_low_upper": 46,
        "baseline_balanced_low": 69,
        "baseline_balanced_upper": 69,
        "status": "BALANCED",
    }
    assert readings[0] == {
        "measured_at": datetime(2026, 1, 14, 21, 26, 54, tzinfo=UTC),
        "hrv_ms": 54,
    }


def test_step_intervals_are_parsed() -> None:
    rows = step_interval_rows(fixture("steps_data"))

    assert len(rows) == 5
    assert rows[3] == {
        "start_at": datetime(2026, 1, 14, 23, 45, tzinfo=UTC),
        "end_at": datetime(2026, 1, 15, 0, 0, tzinfo=UTC),
        "steps": 34,
    }


@pytest.mark.parametrize("payload", [None, {}, [], {"hrvSummary": None, "hrvReadings": None}])
def test_empty_intraday_responses_produce_no_rows(payload: Any) -> None:
    for parse in (
        stress_rows,
        body_battery_rows,
        respiration_rows,
        hrv_summary_rows,
        hrv_reading_rows,
        step_interval_rows,
    ):
        assert parse(payload) == []


def test_one_response_can_feed_several_tables(session: Session) -> None:
    user = make_user(session)

    assert normalise(session, user.id, "stress_data", fixture("stress_data")) == 10
    assert normalise(session, user.id, "hrv_data", fixture("hrv_data")) == 6
    assert normalise(session, user.id, "respiration_data", fixture("respiration_data")) == 5
    assert normalise(session, user.id, "steps_data", fixture("steps_data")) == 5
    session.commit()

    for model, expected in (
        (StressSample, 5),
        (BodyBatterySample, 5),
        (HrvSummary, 1),
        (HrvReading, 5),
        (RespirationSample, 5),
        (StepInterval, 5),
    ):
        assert session.scalar(select(func.count()).select_from(model)) == expected
