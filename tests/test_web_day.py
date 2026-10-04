"""Tests for the day view and the samples within a day that it reads."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from garmin_analyzer.intraday import (
    INTRADAY_METRICS,
    activities_between,
    intraday_series,
    sleeps_between,
)
from garmin_analyzer.models import (
    Activity,
    DailySummary,
    HeartRateSample,
    SleepSession,
    StepInterval,
    User,
)
from garmin_analyzer.tokens import TokenCipher, generate_key
from garmin_analyzer.users import add_user, set_password
from garmin_analyzer.web import dashboards
from garmin_analyzer.web.app import create_app

EMAIL = "runner@example.com"
OTHER_EMAIL = "other@example.com"
PASSWORD = "correct horse battery"  # noqa: S105
CIPHER = TokenCipher(generate_key())
TODAY = date(2026, 9, 30)
MIDNIGHT = datetime(2026, 9, 30, tzinfo=UTC)


def at(hours: float) -> datetime:
    """A moment so many hours after the midnight that starts the day."""
    return MIDNIGHT + timedelta(hours=hours)


def make_user(db: Engine, email: str) -> User:
    with Session(db, expire_on_commit=False) as session:
        user = add_user(session, email)
        session.flush()
        set_password(session, user, PASSWORD)
        session.commit()
        return user


@pytest.fixture
def user(db: Engine) -> User:
    return make_user(db, EMAIL)


@pytest.fixture
def client(db: Engine, user: User, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A browser signed in as the user, on the day the tests are written for."""
    monkeypatch.setattr(dashboards, "today", lambda: TODAY)
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as client:
        client.post("/login", data={"email": EMAIL, "password": PASSWORD})
        yield client


def add_heart_rates(db: Engine, user: User, by_hour: dict[float, int]) -> None:
    with Session(db) as session:
        for hours, bpm in by_hour.items():
            session.add(HeartRateSample(user_id=user.id, measured_at=at(hours), bpm=bpm))
        session.commit()


def add_events(db: Engine, user: User) -> None:
    """A sleep into the morning, a run at noon, and a multi-sport activity with one leg."""
    with Session(db) as session:
        session.add(
            SleepSession(
                user_id=user.id, calendar_date=TODAY, start_at=at(-2), end_at=at(6), sleep_s=1
            )
        )
        session.add_all(
            [
                Activity(
                    user_id=user.id,
                    activity_id=1,
                    start_at=at(12),
                    name="<b>Lunch run</b>",
                    type_key="running",
                    duration_s=1800,
                    elapsed_duration_s=3600,
                ),
                Activity(
                    user_id=user.id,
                    activity_id=2,
                    start_at=at(15),
                    type_key="multi_sport",
                    duration_s=3600,
                    is_parent=True,
                ),
                Activity(
                    user_id=user.id,
                    activity_id=3,
                    start_at=at(15),
                    type_key="open_water_swimming",
                    duration_s=1200,
                ),
                # Ended before the day began.
                Activity(user_id=user.id, activity_id=4, start_at=at(-5), duration_s=3600),
            ]
        )
        session.commit()


def test_samples_are_averaged_per_bucket_from_the_start(db: Engine, user: User) -> None:
    add_heart_rates(db, user, {-0.01: 200, 0: 50, 0.5: 60, 1: 70, 2.99: 80, 3: 200})

    with Session(db) as session:
        series = intraday_series(session, user.id, MIDNIGHT, 3600, 3, ["heart_rate", "stress"])

    # The samples just before the start and at the end fall outside.
    assert series == {"heart_rate": [55, 70, 80], "stress": [None, None, None]}


def test_steps_are_added_up_per_bucket(db: Engine, user: User) -> None:
    with Session(db) as session:
        for quarter, steps in enumerate([100, 200, 300, 400, 50]):
            start = at(quarter / 4)
            session.add(
                StepInterval(
                    user_id=user.id,
                    start_at=start,
                    end_at=start + timedelta(minutes=15),
                    steps=steps,
                )
            )
        session.commit()
        series = intraday_series(session, user.id, MIDNIGHT, 3600, 2, ["steps"])

    assert series == {"steps": [1000, 50]}


def test_events_are_the_sleeps_and_activities_that_overlap(db: Engine, user: User) -> None:
    add_events(db, user)

    with Session(db) as session:
        sleeps = sleeps_between(session, user.id, at(0), at(24))
        activities = activities_between(session, user.id, at(0), at(24))
        afternoon = sleeps_between(session, user.id, at(6), at(24))

    assert [(sleep.start_at, sleep.end_at, sleep.label) for sleep in sleeps] == [
        (at(-2), at(6), "Sleep")
    ]
    assert afternoon == []
    # The run by its name and the time it took with pauses; the leg, not the whole.
    assert [(event.start_at, event.end_at, event.label) for event in activities] == [
        (at(12), at(13), "<b>Lunch run</b>"),
        (at(15), at(15) + timedelta(minutes=20), "Open water swimming"),
    ]


def test_api_gives_buckets_and_events_of_the_signed_in_user_only(
    client: TestClient, db: Engine, user: User
) -> None:
    add_heart_rates(db, user, {0: 50, 0.02: 54})
    add_events(db, user)
    other = make_user(db, OTHER_EMAIL)
    add_heart_rates(db, other, {0: 150})
    add_events(db, other)

    answer = client.get(
        "/api/v1/intraday",
        # A moment with a zone, and one without, which is taken as UTC.
        params={
            "start": "2026-09-30T02:00:00+02:00",
            "end": "2026-09-30T00:10:00",
            "metrics": "heart_rate",
        },
    ).json()

    assert answer == {
        "bucket_seconds": 300,
        "times": ["2026-09-30T00:00:00Z", "2026-09-30T00:05:00Z"],
        "series": {"heart_rate": [52, None]},
        "sleeps": [
            {"start_at": "2026-09-29T22:00:00Z", "end_at": "2026-09-30T06:00:00Z", "label": "Sleep"}
        ],
        "activities": [],
    }


@pytest.mark.parametrize(
    "params",
    [
        {"start": "2026-09-30T00:00:00Z", "end": "2026-09-30T00:00:00Z", "metrics": "steps"},
        {"start": "2026-09-30T00:00:00Z", "end": "2026-10-20T00:00:00Z", "metrics": "steps"},
        {"start": "2026-09-30T00:00:00Z", "end": "2026-10-01T00:00:00Z", "metrics": "resting_hr"},
        {
            "start": "2026-09-30T00:00:00Z",
            "end": "2026-10-07T00:00:00Z",
            "metrics": "steps",
            "bucket": "60",
        },
        {
            "start": "2026-09-30T00:00:00Z",
            "end": "2026-10-01T00:00:00Z",
            "metrics": "steps",
            "bucket": "5",
        },
    ],
)
def test_api_refuses_what_it_cannot_answer(client: TestClient, params: dict[str, str]) -> None:
    assert client.get("/api/v1/intraday", params=params).status_code == 422


def test_intraday_needs_a_signed_in_user(db: Engine) -> None:
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as anonymous:
        response = anonymous.get(
            "/api/v1/intraday",
            params={
                "start": "2026-09-30T00:00:00Z",
                "end": "2026-10-01T00:00:00Z",
                "metrics": "steps",
            },
        )
        page = anonymous.get("/day")

    assert (response.status_code, page.status_code) == (401, 303)


def test_day_shows_the_figures_and_a_chart_per_metric(
    client: TestClient, db: Engine, user: User
) -> None:
    with Session(db) as session:
        session.add(
            DailySummary(
                user_id=user.id,
                calendar_date=TODAY,
                steps=12_345,
                resting_hr=48,
                body_battery_low=20,
                body_battery_high=90,
            )
        )
        session.add(
            SleepSession(
                user_id=user.id,
                calendar_date=TODAY,
                start_at=at(-2),
                end_at=at(6),
                sleep_s=27_000,
                score=82,
            )
        )
        session.commit()

    page = client.get("/day").text

    assert "Wednesday 30 September 2026" in page
    for text in ("12,345", "48 bpm", "20 to 90", "7.5 h, score 82"):
        assert text in page
    # Nothing was summed up for stress.
    assert "<dt" in page
    assert ">Stress</dt>" not in page
    assert page.count('data-chart="intraday"') == len(INTRADAY_METRICS)
    assert page.count('data-day="2026-09-30"') == len(INTRADAY_METRICS)
    assert (
        'data-src="/api/v1/intraday?metrics=heart_rate,stress,body_battery,respiration,hrv'
        '&amp;bucket=300"'
    ) in page
    assert 'data-src="/api/v1/intraday?metrics=steps&amp;bucket=900"' in page
    assert 'data-metrics="steps" data-unit="" data-style="bar"' in page
    assert 'href="?date=2026-09-29">Previous' in page
    # There is no day after the latest one.
    assert 'aria-disabled="true">Next' in page
    assert 'aria-current="page">Day' in page


def test_an_earlier_day_leads_on_to_the_next_and_to_today(client: TestClient) -> None:
    page = client.get("/day", params={"date": "2026-09-28"}).text

    assert "Monday 28 September 2026" in page
    assert 'href="?date=2026-09-27">Previous' in page
    assert 'href="?date=2026-09-29">Next' in page
    assert 'href="/day">Today' in page
    assert "<dt" not in page


@pytest.mark.parametrize("asked", ["2026-10-15", "yesterday", "<script>"])
def test_a_day_that_cannot_be_shown_is_the_latest_one(client: TestClient, asked: str) -> None:
    page = client.get("/day", params={"date": asked}).text

    assert "Wednesday 30 September 2026" in page
    assert asked not in page


def test_every_chart_of_the_day_names_a_known_metric() -> None:
    assert {key for key, _ in dashboards.DAY_CHARTS} == set(INTRADAY_METRICS)
    assert {*dashboards.DAY_METRICS, "steps"} == set(INTRADAY_METRICS)
