import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from garmin_analyzer.db import make_session_factory
from garmin_analyzer.models import Activity, ActivityLap, ActivityZone, RawFile, User
from garmin_analyzer.normalise import normalise
from garmin_analyzer.normalise_activities import (
    activity_rows,
    hr_zone_rows,
    lap_rows,
    power_zone_rows,
)

FIXTURES = Path(__file__).parent / "fixtures" / "garmin"


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


def test_activity_list_is_parsed() -> None:
    rows = activity_rows(fixture("activities"))

    assert [(row["activity_id"], row["type_key"], row["is_parent"]) for row in rows] == [
        (1, "running", False),
        (14, "multi_sport", True),
        (18, "cycling", False),
        (20, "cycling", False),
        (22, "running", False),
    ]
    first = rows[0]
    assert first["start_at"] == datetime(2026, 1, 15, 15, 36, 16, tzinfo=UTC)
    assert first["distance_m"] == 5546.2
    assert first["duration_s"] == 3110.5
    assert first["avg_hr"] == 190.22
    assert first["avg_cadence"] == 227.65
    assert first["training_load"] == 124.45
    assert first["training_effect_label"] == "LACTATE_THRESHOLD"
    assert first["lap_count"] == 10


def test_single_activity_entry_is_parsed() -> None:
    (row,) = activity_rows(fixture("activities")[0])

    assert row["activity_id"] == 1


def test_cadence_uses_the_field_of_the_sport() -> None:
    entry = fixture("activities")[2] | {"averageBikingCadenceInRevPerMinute": 88.0}

    (row,) = activity_rows(entry)

    assert (row["type_key"], row["avg_cadence"]) == ("cycling", 88.0)


def test_activity_without_cadence_has_none() -> None:
    assert activity_rows(fixture("activities")[2])[0]["avg_cadence"] is None


def test_laps_are_parsed() -> None:
    rows = lap_rows(fixture("activity_splits"))

    assert [row["lap_index"] for row in rows] == [1, 2, 3, 4, 5]
    second = rows[1]
    assert second["activity_id"] == 1
    assert second["start_at"] == datetime(2026, 1, 15, 15, 26, 25, tzinfo=UTC)
    assert second["distance_m"] == 830.55
    assert second["intensity_type"] == "ACTIVE"
    assert second["avg_cadence"] == 196.68


def test_zones_take_the_activity_from_the_resource_key() -> None:
    hr = hr_zone_rows(fixture("activity_hr_in_timezones"), "42")
    power = power_zone_rows(fixture("activity_power_in_timezones"), "42")

    assert hr[0] == {
        "activity_id": 42,
        "kind": "hr",
        "zone_number": 1,
        "seconds": 19.96,
        "low_boundary": 124,
    }
    assert [zone["zone_number"] for zone in power] == [1, 2, 3, 4, 5]
    assert {zone["kind"] for zone in power} == {"power"}


def test_zones_without_an_activity_id_produce_no_rows() -> None:
    assert hr_zone_rows(fixture("activity_hr_in_timezones"), "-") == []


@pytest.mark.parametrize("payload", [None, {}, [], [{}], {"lapDTOs": None}])
def test_empty_activity_responses_produce_no_rows(payload: Any) -> None:
    assert activity_rows(payload) == []
    assert lap_rows(payload) == []
    assert hr_zone_rows(payload, "42") == []


def test_activity_responses_are_stored(session: Session, user: User) -> None:
    hr_zones = fixture("activity_hr_in_timezones")
    power_zones = fixture("activity_power_in_timezones")

    assert normalise(session, user.id, "activity_summary", fixture("activities")) == 5
    assert normalise(session, user.id, "activity_splits", fixture("activity_splits")) == 5
    assert normalise(session, user.id, "activity_hr_in_timezones", hr_zones, "1") == 5
    assert normalise(session, user.id, "activity_power_in_timezones", power_zones, "1") == 5
    session.commit()

    assert session.scalar(select(func.count()).select_from(Activity)) == 5
    assert session.scalar(select(func.count()).select_from(ActivityLap)) == 5
    kinds = session.execute(
        select(ActivityZone.kind, func.count()).group_by(ActivityZone.kind)
    ).all()
    assert sorted(tuple(row) for row in kinds) == [("hr", 5), ("power", 5)]


def test_refetching_an_activity_updates_it(session: Session, user: User) -> None:
    entry = fixture("activities")[0]
    normalise(session, user.id, "activity_summary", entry)

    # Renamed in Garmin Connect after the first sync.
    normalise(session, user.id, "activity_summary", entry | {"activityName": "Morning run"})
    session.commit()

    assert session.scalars(select(Activity.name)).all() == ["Morning run"]


def test_raw_file_round_trip_and_uniqueness(session: Session, user: User) -> None:
    archive = b"PK\x03\x04 not a real archive"
    session.add(
        RawFile(user_id=user.id, kind="activity_original", resource_key="1", content=archive)
    )
    session.commit()
    session.expire_all()

    assert session.scalars(select(RawFile.content)).one() == archive

    session.add(RawFile(user_id=user.id, kind="activity_original", resource_key="1", content=b""))
    with pytest.raises(IntegrityError):
        session.commit()
