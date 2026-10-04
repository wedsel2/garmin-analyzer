"""Tests for the overview page and the JSON API its charts read."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from garmin_analyzer.metrics import DAILY_METRICS, daily_series
from garmin_analyzer.models import (
    Activity,
    DailySummary,
    GarminLink,
    SleepSession,
    TrainingReadiness,
    TrainingStatus,
    User,
)
from garmin_analyzer.tokens import TokenCipher, generate_key
from garmin_analyzer.users import add_user, set_password
from garmin_analyzer.web import overview
from garmin_analyzer.web.app import create_app
from garmin_analyzer.web.shared import duration, kilometres

EMAIL = "runner@example.com"
OTHER_EMAIL = "other@example.com"
PASSWORD = "correct horse battery"  # noqa: S105
CIPHER = TokenCipher(generate_key())
TODAY = datetime.now(UTC).date()


def days_ago(days: int) -> date:
    return TODAY - timedelta(days=days)


def make_user(db: Engine, email: str) -> User:
    with Session(db, expire_on_commit=False) as session:
        user = add_user(session, email)
        session.flush()
        set_password(session, user, PASSWORD)
        session.add(GarminLink(user_id=user.id, encrypted_tokens=b"-"))
        session.commit()
        return user


@pytest.fixture
def user(db: Engine) -> User:
    return make_user(db, EMAIL)


@pytest.fixture
def client(db: Engine, user: User) -> Iterator[TestClient]:
    """A browser signed in as the user."""
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as client:
        client.post("/login", data={"email": EMAIL, "password": PASSWORD})
        yield client


def add_days(db: Engine, user: User, resting_hr: dict[int, int | None]) -> None:
    """Daily summaries with the given resting heart rate, keyed by days ago."""
    with Session(db) as session:
        for ago, value in resting_hr.items():
            session.add(
                DailySummary(user_id=user.id, calendar_date=days_ago(ago), resting_hr=value)
            )
        session.commit()


def test_daily_series_has_a_value_or_none_for_every_day(db: Engine, user: User) -> None:
    add_days(db, user, {3: 50, 1: 52, 0: None})

    with Session(db) as session:
        series = daily_series(session, user.id, days_ago(3), TODAY, ["resting_hr", "steps"])

    assert series == {"resting_hr": [50, None, 52, None], "steps": [None] * 4}


def test_daily_series_takes_the_last_reading_of_a_day(db: Engine, user: User) -> None:
    with Session(db) as session:
        for hour, score in ((6, 40), (18, 70), (20, None)):
            session.add(
                TrainingReadiness(
                    user_id=user.id,
                    measured_at=datetime(TODAY.year, TODAY.month, TODAY.day, hour, tzinfo=UTC),
                    calendar_date=TODAY,
                    score=score,
                )
            )
        session.commit()
        series = daily_series(session, user.id, TODAY, TODAY, ["training_readiness"])

    assert series == {"training_readiness": [70]}


def test_api_returns_the_days_of_the_signed_in_user_only(
    client: TestClient, db: Engine, user: User
) -> None:
    add_days(db, user, {1: 50, 0: 52})
    add_days(db, make_user(db, OTHER_EMAIL), {1: 90, 0: 91})

    response = client.get(
        "/api/v1/daily",
        params={"start": str(days_ago(2)), "end": str(TODAY), "metrics": "resting_hr, steps"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "dates": [str(days_ago(2)), str(days_ago(1)), str(TODAY)],
        "series": {"resting_hr": [None, 50, 52], "steps": [None, None, None]},
    }


def test_api_needs_a_signed_in_user(db: Engine) -> None:
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as anonymous:
        response = anonymous.get(
            "/api/v1/daily", params={"start": str(TODAY), "end": str(TODAY), "metrics": "steps"}
        )

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("start", "end", "metrics"),
    [
        (TODAY, TODAY, "steps,password_hash"),
        (TODAY, TODAY, " , "),
        (TODAY, days_ago(1), "steps"),
        (days_ago(4000), TODAY, "steps"),
    ],
)
def test_api_refuses_what_it_cannot_answer(
    client: TestClient, start: date, end: date, metrics: str
) -> None:
    response = client.get(
        "/api/v1/daily", params={"start": str(start), "end": str(end), "metrics": metrics}
    )

    assert response.status_code == 422


def test_api_is_described_without_the_pages(client: TestClient) -> None:
    paths = client.get("/api/v1/openapi.json").json()["paths"]

    assert list(paths) == [
        "/api/v1/daily",
        "/api/v1/weekly",
        "/api/v1/nights",
        "/api/v1/intraday",
    ]


def test_tile_compares_the_latest_value_with_the_days_before(db: Engine, user: User) -> None:
    add_days(db, user, {5: 50, 4: 50, 3: 50, 1: 56, 0: None})

    with Session(db) as session:
        tiles = {tile.key: tile for tile in overview.tiles(session, user.id, TODAY)}

    resting = tiles["resting_hr"]
    assert (resting.value, resting.day, resting.average) == (56, days_ago(1), 50)
    # A higher resting heart rate is the wrong direction.
    assert (resting.delta, resting.verdict) == (6, "worse")
    assert (tiles["steps"].value, tiles["steps"].delta, tiles["steps"].verdict) == (None,) * 3


def test_tile_needs_a_few_days_before_it_compares(db: Engine, user: User) -> None:
    add_days(db, user, {2: 50, 1: 50, 0: 56})

    with Session(db) as session:
        tiles = {tile.key: tile for tile in overview.tiles(session, user.id, TODAY)}

    assert (tiles["resting_hr"].value, tiles["resting_hr"].delta) == (56, None)


def test_tile_carries_garmins_word_for_the_value(db: Engine, user: User) -> None:
    with Session(db) as session:
        session.add(
            TrainingStatus(
                user_id=user.id, calendar_date=TODAY, acute_load=300, status="PRODUCTIVE_2"
            )
        )
        session.commit()
        tiles = {tile.key: tile for tile in overview.tiles(session, user.id, TODAY)}

    assert tiles["acute_load"].note == "Productive"
    # More or less load is not better or worse in itself.
    assert tiles["acute_load"].verdict is None


def test_every_tile_is_a_known_metric() -> None:
    assert set(overview.TILES) <= set(DAILY_METRICS)


def test_day_label_names_today_and_yesterday() -> None:
    today = date(2026, 10, 4)

    assert overview.day_label(today, today) == "Today"
    assert overview.day_label(date(2026, 10, 3), today) == "Yesterday"
    assert overview.day_label(date(2026, 9, 28), today) == "28 Sep"


def test_lengths_and_times_are_written_for_people() -> None:
    assert (kilometres(10_240), kilometres(None)) == ("10.2 km", "")
    assert (duration(3_723.4), duration(605), duration(None)) == ("1:02:03", "10:05", "")


def test_overview_shows_tiles_charts_and_recent_activities(
    client: TestClient, db: Engine, user: User
) -> None:
    add_days(db, user, {4: 50, 3: 50, 2: 50, 1: 50, 0: 47})
    with Session(db) as session:
        session.add(
            SleepSession(
                user_id=user.id,
                calendar_date=TODAY,
                start_at=datetime.now(UTC) - timedelta(hours=8),
                end_at=datetime.now(UTC),
                score=81,
                score_qualifier="GOOD",
            )
        )
        session.add(
            Activity(
                user_id=user.id,
                activity_id=1,
                start_at=datetime.now(UTC) - timedelta(hours=2),
                type_key="trail_running",
                name="Dunes",
                distance_m=12_345,
                duration_s=4_000,
                avg_hr=148,
            )
        )
        session.commit()

    page = client.get("/").text

    assert "Today · Good" in page
    assert "3 below your 4-week average" in page
    assert "No data in the last 4 weeks" in page
    assert 'data-chart="sparkline"' in page
    assert f"/api/v1/daily?start={days_ago(28)}&amp;end={TODAY}&amp;metrics=sleep_score," in page
    assert 'data-metric="resting_hr"' in page
    assert 'data-average="50.0"' in page
    assert '<script src="/static/charts.js" defer></script>' in page
    assert "Dunes" in page
    assert "Trail running" in page
    assert "12.3 km" in page
    assert "1:06:40" in page
    assert "148 bpm" in page


def test_overview_without_a_link_asks_to_link_and_shows_no_tiles(db: Engine) -> None:
    with Session(db) as session:
        unlinked = add_user(session, OTHER_EMAIL)
        session.flush()
        set_password(session, unlinked, PASSWORD)
        session.commit()
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as client:
        client.post("/login", data={"email": OTHER_EMAIL, "password": PASSWORD})
        page = client.get("/").text

    assert "No Garmin account is linked yet" in page
    assert "data-chart" not in page
    assert "Recent activities" not in page
