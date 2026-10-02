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
    FitnessAge,
    PowerThreshold,
    RacePrediction,
    TrainingReadiness,
    TrainingStatus,
    User,
    Vo2Max,
)
from garmin_analyzer.normalise import normalise
from garmin_analyzer.normalise_training import (
    fitness_age_rows,
    power_threshold_rows,
    race_prediction_rows,
    training_readiness_rows,
    training_status_rows,
    vo2max_from_training_status_rows,
    vo2max_rows,
)

FIXTURES = Path(__file__).parent / "fixtures" / "garmin"

PARSERS = (
    fitness_age_rows,
    power_threshold_rows,
    race_prediction_rows,
    training_readiness_rows,
    training_status_rows,
    vo2max_from_training_status_rows,
    vo2max_rows,
)


def fixture(name: str) -> Any:
    """A synthetic Garmin response made by scripts/scrub_fixture.py."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def session(db: Engine) -> Iterator[Session]:
    with make_session_factory(db)() as session:
        yield session


@pytest.fixture
def user(session: Session) -> User:
    user = User(email="runner@example.com", password_hash="not-a-real-hash")  # noqa: S106
    session.add(user)
    session.commit()
    return user


def test_training_readiness_is_parsed() -> None:
    (row,) = training_readiness_rows(fixture("training_readiness"))

    assert row["measured_at"] == datetime(2026, 1, 15, 5, 51, 55, tzinfo=UTC)
    assert row["calendar_date"] == date(2026, 1, 14)
    assert row["score"] == 45
    assert row["level"] == "LOW"
    assert row["feedback"] == "HIGH_RECOVERY_NEEDS"
    assert row["recovery_time_min"] == 1397
    assert row["hrv_factor_pct"] == 73


def test_training_status_is_parsed() -> None:
    (row,) = training_status_rows(fixture("training_status"))

    assert row == {
        "calendar_date": date(2026, 1, 15),
        "status_code": 10,
        "status": "PRODUCTIVE_2",
        "sport": "RUNNING",
        "fitness_trend": 1,
        "acute_load": 974,
        "chronic_load": 471,
        "acwr": 0.74,
        "acwr_status": "OPTIMAL",
        "load_aerobic_low": 547.98,
        "load_aerobic_high": 1099.52,
        "load_anaerobic": 270.43,
        "load_balance": "BALANCED",
    }


def test_training_status_prefers_the_primary_device() -> None:
    payload = fixture("training_status")
    by_device = payload["mostRecentTrainingStatus"]["latestTrainingStatusData"]
    (primary,) = by_device.values()
    by_device["99"] = primary | {"primaryTrainingDevice": False, "trainingStatus": 1}
    payload["mostRecentTrainingStatus"]["latestTrainingStatusData"] = dict(
        reversed(by_device.items())
    )

    (row,) = training_status_rows(payload)

    assert row["status_code"] == 10


def test_training_status_without_load_balance_still_parses() -> None:
    payload = fixture("training_status")
    payload["mostRecentTrainingLoadBalance"] = None

    (row,) = training_status_rows(payload)

    assert row["status"] == "PRODUCTIVE_2"
    assert row["load_balance"] is None


def test_vo2max_is_parsed_from_a_range() -> None:
    rows = vo2max_rows(fixture("max_metrics"))

    assert rows == [
        {
            "calendar_date": date(2026, 1, 13),
            "running": 24.31,
            "cycling": None,
            "heat_acclimation_pct": 21,
            "altitude_acclimation": 0,
        },
        {
            "calendar_date": date(2026, 1, 15),
            "running": 46.23,
            "cycling": None,
            "heat_acclimation_pct": 35,
            "altitude_acclimation": 0,
        },
    ]


def test_vo2max_is_also_taken_from_training_status() -> None:
    (row,) = vo2max_from_training_status_rows(fixture("training_status"))

    assert (row["calendar_date"], row["running"]) == (date(2026, 1, 14), 58.4)


def test_cycling_only_vo2max_uses_the_cycling_date() -> None:
    payload = {"generic": None, "cycling": {"calendarDate": "2026-01-10", "vo2MaxPreciseValue": 51}}

    (row,) = vo2max_rows(payload)

    assert (row["calendar_date"], row["running"], row["cycling"]) == (date(2026, 1, 10), None, 51)


def test_race_predictions_are_parsed() -> None:
    assert race_prediction_rows(fixture("race_predictions")) == [
        {
            "calendar_date": date(2026, 1, 14),
            "time_5k_s": 2109,
            "time_10k_s": 3380,
            "time_half_marathon_s": 4271,
            "time_marathon_s": 15558,
        }
    ]


def test_fitness_age_is_parsed() -> None:
    assert fitness_age_rows(fixture("fitnessage_data")) == [
        {
            "calendar_date": date(2026, 1, 15),
            "fitness_age": 22.52,
            "chronological_age": 35,
            "achievable_fitness_age": 11.98,
        }
    ]


def test_power_thresholds_come_from_two_responses() -> None:
    assert power_threshold_rows(fixture("cycling_ftp")) == [
        {
            "sport": "CYCLING",
            "calendar_date": date(2026, 1, 15),
            "ftp_watts": 252,
            "power_to_weight": None,
        }
    ]
    assert power_threshold_rows(fixture("lactate_threshold")) == [
        {
            "sport": "RUNNING",
            "calendar_date": date(2026, 1, 15),
            "ftp_watts": 473,
            "power_to_weight": 4.63,
        }
    ]


def test_power_threshold_without_a_value_is_skipped() -> None:
    payload = fixture("cycling_ftp") | {"functionalThresholdPower": None}

    assert power_threshold_rows(payload) == []


@pytest.mark.parametrize(
    "payload",
    [None, {}, [], [{}], {"mostRecentTrainingStatus": None, "mostRecentVO2Max": None}],
)
def test_empty_training_responses_produce_no_rows(payload: Any) -> None:
    for parse in PARSERS:
        assert parse(payload) == []


def test_training_responses_are_stored(session: Session, user: User) -> None:
    for endpoint, rows in (
        ("training_readiness", 1),
        ("training_status", 2),
        ("max_metrics", 2),
        ("race_predictions", 1),
        ("fitnessage_data", 1),
        ("cycling_ftp", 1),
        ("lactate_threshold", 1),
    ):
        assert normalise(session, user.id, endpoint, fixture(endpoint)) == rows
    session.commit()

    for model, expected in (
        (TrainingReadiness, 1),
        (TrainingStatus, 1),
        # Two days from the range plus a third from the training status response.
        (Vo2Max, 3),
        (RacePrediction, 1),
        (FitnessAge, 1),
        (PowerThreshold, 2),
    ):
        assert session.scalar(select(func.count()).select_from(model)) == expected


def test_duplicate_days_in_one_response_keep_the_last(session: Session, user: User) -> None:
    first, second = fixture("max_metrics")
    second["generic"]["calendarDate"] = first["generic"]["calendarDate"]

    assert normalise(session, user.id, "max_metrics", [first, second]) == 1
    session.commit()

    assert session.scalars(select(Vo2Max.running)).all() == [46.23]
