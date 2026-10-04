"""Tests for the recovery and sleep pages and the series they read."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from garmin_analyzer.metrics import (
    DAILY_METRICS,
    daily_series,
    first_day,
    mean,
    rolling_series,
    weekly_series,
)
from garmin_analyzer.models import DailySummary, SleepSession, User
from garmin_analyzer.tokens import TokenCipher, generate_key
from garmin_analyzer.users import add_user, set_password
from garmin_analyzer.web import dashboards, shared
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


def add_resting_hr(db: Engine, user: User, by_days_ago: dict[int, int]) -> None:
    with Session(db) as session:
        for ago, value in by_days_ago.items():
            session.add(
                DailySummary(user_id=user.id, calendar_date=days_ago(ago), resting_hr=value)
            )
        session.commit()


def add_sleep(db: Engine, user: User, ago: int, hours: float = 8, score: int = 80) -> SleepSession:
    end = datetime(TODAY.year, TODAY.month, TODAY.day, 5, 30, tzinfo=UTC) - timedelta(days=ago)
    sleep = SleepSession(
        user_id=user.id,
        calendar_date=days_ago(ago),
        start_at=end - timedelta(hours=hours),
        end_at=end,
        sleep_s=int(hours * 3600),
        deep_s=5400,
        score=score,
    )
    with Session(db, expire_on_commit=False) as session:
        session.add(sleep)
        session.commit()
    return sleep


def test_mean_skips_missing_values_and_can_ask_for_enough() -> None:
    assert mean([1, None, 2]) == 1.5
    assert mean([None, None]) is None
    assert mean([1, None, 2], at_least=3) is None


def test_a_metric_in_hours_is_scaled_from_the_stored_seconds(db: Engine, user: User) -> None:
    add_sleep(db, user, 0, hours=7.5)

    with Session(db) as session:
        series = daily_series(session, user.id, TODAY, TODAY, ["sleep_duration", "sleep_deep"])

    assert series == {"sleep_duration": [7.5], "sleep_deep": [1.5]}


def test_rolling_average_reads_the_days_before_the_period(db: Engine, user: User) -> None:
    add_resting_hr(db, user, {4: 40, 3: 50, 2: 60, 0: 70})

    with Session(db) as session:
        rolling = rolling_series(session, user.id, days_ago(1), TODAY, ["resting_hr"], 3)

    # Yesterday: the days 3, 2 and 1 ago, of which two have a value. Today: 2, 1 and 0 ago.
    assert rolling == {"resting_hr": [55, 65]}


def test_rolling_average_needs_more_than_half_of_the_window(db: Engine, user: User) -> None:
    add_resting_hr(db, user, {0: 70})

    with Session(db) as session:
        rolling = rolling_series(session, user.id, TODAY, TODAY, ["resting_hr"], 3)

    assert rolling == {"resting_hr": [None]}


def test_weekly_average_runs_from_monday_and_stops_at_the_end(db: Engine, user: User) -> None:
    # Days ago 9 is Monday the 21st, 2 is Monday the 28th.
    add_resting_hr(db, user, {9: 50, 8: 52, 2: 60, 0: 62})

    with Session(db) as session:
        mondays, series = weekly_series(session, user.id, days_ago(7), TODAY, ["resting_hr"])

    assert mondays == [date(2026, 9, 21), date(2026, 9, 28)]
    assert series == {"resting_hr": [51, 61]}


def test_first_day_is_the_earliest_of_summaries_and_sleeps(db: Engine, user: User) -> None:
    with Session(db) as session:
        assert first_day(session, user.id) is None
    add_resting_hr(db, user, {3: 50})
    add_sleep(db, user, 10)

    with Session(db) as session:
        assert first_day(session, user.id) == days_ago(10)


def test_api_gives_the_rolling_average_when_asked(
    client: TestClient, db: Engine, user: User
) -> None:
    add_resting_hr(db, user, {2: 50, 1: 52, 0: 54})

    answer = client.get(
        "/api/v1/daily",
        params={"start": str(days_ago(1)), "end": str(TODAY), "metrics": "resting_hr"},
    ).json()
    rolled = client.get(
        "/api/v1/daily",
        params={
            "start": str(days_ago(1)),
            "end": str(TODAY),
            "metrics": "resting_hr",
            "rolling": 3,
        },
    ).json()

    assert "rolling" not in answer
    assert rolled["rolling"] == {"resting_hr": [51, 52]}
    assert rolled["series"] == {"resting_hr": [52, 54]}


def test_api_gives_weekly_averages_of_the_signed_in_user_only(
    client: TestClient, db: Engine, user: User
) -> None:
    add_resting_hr(db, user, {1: 50, 0: 52})
    add_resting_hr(db, make_user(db, OTHER_EMAIL), {1: 90, 0: 92})

    response = client.get(
        "/api/v1/weekly",
        params={"start": str(days_ago(1)), "end": str(TODAY), "metrics": "resting_hr"},
    )

    assert response.json() == {"dates": ["2026-09-28"], "series": {"resting_hr": [51]}}


def test_api_gives_bed_and_wake_times_of_the_signed_in_user_only(
    client: TestClient, db: Engine, user: User
) -> None:
    add_sleep(db, user, 0, hours=8)
    add_sleep(db, make_user(db, OTHER_EMAIL), 1)

    response = client.get("/api/v1/nights", params={"start": str(days_ago(1)), "end": str(TODAY)})

    assert response.json() == {
        "dates": ["2026-09-29", "2026-09-30"],
        "start_at": [None, "2026-09-29T21:30:00Z"],
        "end_at": [None, "2026-09-30T05:30:00Z"],
    }


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/weekly", {"start": "2026-09-30", "end": "2026-09-29", "metrics": "steps"}),
        ("/api/v1/weekly", {"start": "2026-09-29", "end": "2026-09-30", "metrics": "email"}),
        ("/api/v1/nights", {"start": "2010-01-01", "end": "2026-09-30"}),
        (
            "/api/v1/daily",
            {"start": "2026-09-29", "end": "2026-09-30", "metrics": "steps", "rolling": 400},
        ),
    ],
)
def test_api_refuses_what_it_cannot_answer(
    client: TestClient, path: str, params: dict[str, str]
) -> None:
    assert client.get(path, params=params).status_code == 422


@pytest.mark.parametrize("path", ["/api/v1/weekly", "/api/v1/nights", "/recovery", "/sleep"])
def test_dashboards_need_a_signed_in_user(db: Engine, path: str) -> None:
    make_user(db, EMAIL)
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as anonymous:
        response = anonymous.get(path, params={"start": "2026-09-29", "end": "2026-09-30"})

    assert response.status_code in (303, 401)
    assert "resting" not in response.text.lower()


def test_a_period_asked_for_by_htmx_without_a_session_leads_to_signing_in(db: Engine) -> None:
    make_user(db, EMAIL)
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as anonymous:
        response = anonymous.get("/recovery", headers={"HX-Request": "true"})

    assert (response.status_code, response.headers["hx-redirect"]) == (204, "/login")


def test_recovery_shows_averages_and_daily_charts_for_four_weeks(
    client: TestClient, db: Engine, user: User
) -> None:
    add_resting_hr(db, user, {40: 90, 3: 50, 0: 53})

    page = client.get("/recovery").text

    # The value of 40 days ago is outside the period.
    assert "52</span>" in page
    assert "bpm on average" in page
    assert (
        'data-chart="trend" data-src="/api/v1/daily?start=2026-09-03&amp;end=2026-09-30'
        "&amp;metrics=resting_hr&amp;rolling=7"
    ) in page
    assert 'data-per="day"' in page
    assert 'aria-current="true">4 weeks' in page
    assert 'aria-current="page">Recovery' in page
    # Nothing was measured for the other charts.
    assert page.count("No data in this period.") == 2
    assert 'data-metrics="body_battery_low,body_battery_high"' in page


def test_a_long_period_shows_weekly_averages_from_the_first_day(
    client: TestClient, db: Engine, user: User
) -> None:
    add_resting_hr(db, user, {400: 48, 0: 52})

    year = client.get("/recovery", params={"period": "1y"}).text
    everything = client.get("/recovery", params={"period": "all"}).text

    assert "/api/v1/weekly?start=2025-10-01&amp;end=2026-09-30&amp;metrics=resting_hr" in year
    assert 'data-per="week"' in year
    assert "rolling" not in year
    assert f"/api/v1/weekly?start={days_ago(400)}&amp;end=2026-09-30" in everything
    assert "50</span>" in everything


def test_an_unknown_period_is_the_default_one(client: TestClient) -> None:
    page = client.get("/recovery", params={"period": "<script>"}).text

    assert 'aria-current="true">4 weeks' in page
    assert "<script>" not in page.replace('<script src="/static/', "")


def test_sleep_shows_hours_stages_and_nights(client: TestClient, db: Engine, user: User) -> None:
    add_sleep(db, user, 1, hours=7, score=70)
    add_sleep(db, user, 0, hours=8, score=80)

    page = client.get("/sleep", params={"period": "7d"}).text

    assert "7.5</span>" in page
    assert "h on average" in page
    assert 'data-metrics="sleep_deep,sleep_light,sleep_rem,sleep_awake"' in page
    assert 'data-labels="Deep,Light,REM,Awake"' in page
    assert "75</span>" in page
    assert 'data-chart="nights" data-src="/api/v1/nights?start=2026-09-24&amp;end=2026-09-30"' in (
        page
    )


def test_bed_and_wake_times_are_left_out_of_long_periods(
    client: TestClient, db: Engine, user: User
) -> None:
    add_sleep(db, user, 0)

    page = client.get("/sleep", params={"period": "1y"}).text

    assert 'data-chart="nights"' not in page
    assert "Shown for periods up to 3 months." in page


def test_every_chart_names_known_metrics() -> None:
    for chart in (*dashboards.RECOVERY, *dashboards.SLEEP):
        assert {*chart.metrics, *filter(None, [chart.headline])} <= set(DAILY_METRICS)


def test_today_is_a_date() -> None:
    assert isinstance(shared.today(), date)
