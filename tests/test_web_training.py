"""Tests for the training page and what it reads beyond daily metrics."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from garmin_analyzer import training
from garmin_analyzer.metrics import DAILY_METRICS, daily_series
from garmin_analyzer.models import (
    Activity,
    RacePrediction,
    TrainingReadiness,
    TrainingStatus,
    User,
    Vo2Max,
)
from garmin_analyzer.tokens import TokenCipher, generate_key
from garmin_analyzer.users import add_user, set_password
from garmin_analyzer.web import dashboards
from garmin_analyzer.web.app import create_app

EMAIL = "runner@example.com"
OTHER_EMAIL = "other@example.com"
PASSWORD = "correct horse battery"  # noqa: S105
CIPHER = TokenCipher(generate_key())
# A Wednesday.
TODAY = date(2026, 9, 30)


def days_ago(days: int) -> date:
    return TODAY - timedelta(days=days)


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


def add_activities(db: Engine, user: User, activities: list[tuple[int, str | None, float]]) -> None:
    """Activities given as days ago, sport and hours, begun at noon."""
    with Session(db) as session:
        for number, (ago, sport, hours) in enumerate(activities):
            day = days_ago(ago)
            session.add(
                Activity(
                    user_id=user.id,
                    activity_id=number + 1,
                    start_at=datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
                    type_key=sport,
                    duration_s=hours * 3600,
                    is_parent=sport == "multi_sport",
                )
            )
        session.commit()


def test_hours_per_week_are_split_by_the_sports_with_the_most_time(db: Engine, user: User) -> None:
    add_activities(
        db,
        user,
        [
            # The week of Monday the 21st, then the one of the 28th.
            (9, "running", 1),
            (8, "cycling", 3),
            (7, "running", 0.5),
            (2, "trail_running", 2),
            (1, "yoga", 0.25),
            (0, "hiking", 0.5),
            # Its legs count, the whole does not.
            (0, "multi_sport", 5),
        ],
    )

    with Session(db) as session:
        mondays, hours = training.weekly_hours(session, user.id, days_ago(7), TODAY)

    assert mondays == [date(2026, 9, 21), date(2026, 9, 28)]
    assert hours == {
        "Cycling": [3, 0],
        "Trail running": [0, 2],
        "Running": [1.5, 0],
        "Other": [0, 0.75],
    }


def test_few_sports_need_no_other(db: Engine, user: User) -> None:
    add_activities(db, user, [(0, None, 1)])

    with Session(db) as session:
        assert training.weekly_hours(session, user.id, TODAY, TODAY)[1] == {"Activity": [1]}
        assert training.weekly_hours(session, user.id, days_ago(30), days_ago(20))[1] == {}


def test_minutes_per_day_add_up_and_leave_days_without_activities_empty(
    db: Engine, user: User
) -> None:
    add_activities(db, user, [(2, "running", 0.5), (2, "cycling", 1), (0, "running", 0.25)])

    with Session(db) as session:
        minutes = training.daily_minutes(session, user.id, days_ago(2), TODAY)

    assert minutes == [90, None, 15]


def test_predictions_compare_the_latest_with_the_first_in_the_period(
    db: Engine, user: User
) -> None:
    with Session(db) as session:
        session.add_all(
            [
                RacePrediction(user_id=user.id, calendar_date=days_ago(40), time_5k_s=1500),
                RacePrediction(
                    user_id=user.id, calendar_date=days_ago(10), time_5k_s=1400, time_10k_s=2900
                ),
                RacePrediction(
                    user_id=user.id, calendar_date=days_ago(1), time_5k_s=1380, time_10k_s=2900
                ),
            ]
        )
        session.commit()
        predictions = training.predictions(session, user.id, days_ago(27), TODAY)

    assert predictions == [
        training.Prediction("5 km", 1380, -20),
        training.Prediction("10 km", 2900, 0),
    ]


def test_latest_readiness_lists_the_factors_that_were_measured(db: Engine, user: User) -> None:
    with Session(db) as session:
        assert training.latest_readiness(session, user.id) is None
        for hour, score in ((6, 40), (18, 62)):
            session.add(
                TrainingReadiness(
                    user_id=user.id,
                    measured_at=datetime(2026, 9, 29, hour, tzinfo=UTC),
                    calendar_date=days_ago(1),
                    score=score,
                    level="MODERATE",
                    sleep_factor_pct=score + 10,
                    hrv_factor_pct=90,
                )
            )
        session.commit()
        readiness = training.latest_readiness(session, user.id)

    assert readiness == training.Readiness(
        days_ago(1), 62, "MODERATE", [("Sleep last night", 72), ("HRV", 90)]
    )


def test_the_optimal_range_of_load_follows_the_chronic_load(db: Engine, user: User) -> None:
    with Session(db) as session:
        session.add(
            TrainingStatus(user_id=user.id, calendar_date=TODAY, acute_load=450, chronic_load=400)
        )
        session.commit()
        series = daily_series(
            session,
            user.id,
            TODAY,
            TODAY,
            ["acute_load", "chronic_load", "load_optimal_low", "load_optimal_high"],
        )

    assert series == {
        "acute_load": [450],
        "chronic_load": [400],
        "load_optimal_low": [320],
        "load_optimal_high": [600],
    }


def test_api_gives_activity_time_of_the_signed_in_user_only(
    client: TestClient, db: Engine, user: User
) -> None:
    add_activities(db, user, [(1, "running", 1.5)])
    add_activities(db, make_user(db, OTHER_EMAIL), [(1, "cycling", 4)])
    params = {"start": str(days_ago(1)), "end": str(TODAY)}

    weeks = client.get("/api/v1/activity-weeks", params=params).json()
    days = client.get("/api/v1/activity-days", params=params).json()

    assert weeks == {"dates": ["2026-09-28"], "series": {"Running": [1.5]}}
    assert days == {"dates": ["2026-09-29", "2026-09-30"], "minutes": [90, None]}


@pytest.mark.parametrize("path", ["/api/v1/activity-weeks", "/api/v1/activity-days"])
def test_api_refuses_a_period_that_is_too_long_and_needs_a_session(
    client: TestClient, db: Engine, path: str
) -> None:
    assert client.get(path, params={"start": "2010-01-01", "end": "2026-09-30"}).status_code == 422
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as anonymous:
        response = anonymous.get(path, params={"start": "2026-09-29", "end": "2026-09-30"})
    assert response.status_code == 401


def test_training_shows_load_predictions_readiness_and_the_calendar(
    client: TestClient, db: Engine, user: User
) -> None:
    with Session(db) as session:
        session.add_all(
            [
                TrainingStatus(
                    user_id=user.id, calendar_date=days_ago(3), acute_load=300, chronic_load=380
                ),
                TrainingStatus(
                    user_id=user.id, calendar_date=TODAY, acute_load=450, chronic_load=400
                ),
                Vo2Max(user_id=user.id, calendar_date=days_ago(5), running=52.3),
                RacePrediction(user_id=user.id, calendar_date=days_ago(9), time_5k_s=1415),
                RacePrediction(user_id=user.id, calendar_date=TODAY, time_5k_s=1380),
                TrainingReadiness(
                    user_id=user.id,
                    measured_at=datetime(2026, 9, 30, 6, tzinfo=UTC),
                    calendar_date=TODAY,
                    score=71,
                    level="HIGH",
                    acwr_factor_pct=88,
                ),
            ]
        )
        session.commit()

    page = client.get("/training").text

    # The latest acute load, not the average of the period.
    assert "450</span>" in page
    assert "latest" in page
    assert (
        'data-chart="lines" data-src="/api/v1/daily?start=2026-09-03&amp;end=2026-09-30'
        '&amp;metrics=acute_load,chronic_load,load_optimal_low,load_optimal_high"'
    ) in page
    assert 'data-band="load_optimal_low,load_optimal_high" data-band-label="Optimal range"' in page
    assert 'data-labels="Acute load,Chronic load"' in page
    assert 'data-metrics="vo2max_running,vo2max_cycling"' in page
    assert 'data-chart="volume" data-src="/api/v1/activity-weeks?start=2026-09-03' in page
    assert "23:00" in page
    assert "0:35 faster" in page
    assert "Today · High" in page
    assert 'value="88" max="100" aria-label="Training load"' in page
    assert (
        'data-chart="calendar" data-src="/api/v1/activity-days?start=2025-10-01&amp;end=2026-09-30"'
    ) in page
    assert 'aria-current="page">Training' in page


def test_training_without_data_says_so(client: TestClient) -> None:
    page = client.get("/training", params={"period": "1y"}).text

    assert "No training readiness collected yet." in page
    assert page.count('<p class="py-8 text-center text-sm opacity-70">No data in this period.') == 3
    # A year shows the charts that are left per week.
    assert "/api/v1/weekly?start=2025-10-01" in page


def test_every_training_chart_names_known_metrics() -> None:
    for chart in dashboards.TRAINING:
        assert {*chart.metrics, *(chart.band or ())} <= set(DAILY_METRICS)
    assert set(training.RACES) <= set(DAILY_METRICS)
    assert all(hasattr(TrainingReadiness, column) for column in training.FACTORS)
