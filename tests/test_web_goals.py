"""Tests for goals: events, weekly goals, their pages and the block on the overview."""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from garmin_analyzer import goals
from garmin_analyzer.goals import GoalError
from garmin_analyzer.models import (
    Activity,
    GarminLink,
    GoalEvent,
    Measure,
    RacePrediction,
    User,
    WeeklyGoal,
)
from garmin_analyzer.tokens import TokenCipher, generate_key
from garmin_analyzer.users import add_user, set_password
from garmin_analyzer.web import goal_pages, shared
from garmin_analyzer.web.app import create_app

EMAIL = "runner@example.com"
OTHER_EMAIL = "other@example.com"
PASSWORD = "correct horse battery"  # noqa: S105
CIPHER = TokenCipher(generate_key())
# A Wednesday.
TODAY = date(2026, 9, 30)
HALF_MARATHON = {
    "name": "Dune half",
    "day": "2026-10-25",
    "sport": "running",
    "distance": "21,1",
    "target_time": "1:45:00",
}


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
def client(db: Engine, user: User, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A browser signed in as the user, on the day the tests are written for."""
    monkeypatch.setattr(goal_pages, "today", lambda: TODAY)
    monkeypatch.setattr(shared, "today", lambda: TODAY)
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as client:
        client.post("/login", data={"email": EMAIL, "password": PASSWORD})
        yield client


def add_activities(
    db: Engine, user: User, activities: list[tuple[int, str | None, float, float | None]]
) -> None:
    """Activities given as days ago, sport, hours and kilometres, begun at noon."""
    with Session(db) as session:
        first = session.scalar(select(func.count()).select_from(Activity)) or 0
        for number, (ago, sport, hours, km) in enumerate(activities):
            day = days_ago(ago)
            session.add(
                Activity(
                    user_id=user.id,
                    activity_id=first + number + 1,
                    start_at=datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
                    type_key=sport,
                    name=f"Activity {first + number + 1}",
                    duration_s=hours * 3600,
                    distance_m=None if km is None else km * 1000,
                    is_parent=sport == "multi_sport",
                )
            )
        session.commit()


def add_weekly_goal(
    db: Engine, user: User, measure: Measure, target: float, sport: str | None = None
) -> uuid.UUID:
    with Session(db) as session:
        goal = WeeklyGoal(user_id=user.id, measure=measure, target=target, sport=sport)
        session.add(goal)
        session.commit()
        return goal.id


def add_event(db: Engine, user: User, day: date, **fields: object) -> uuid.UUID:
    with Session(db) as session:
        event = GoalEvent(user_id=user.id, event_date=day, **{"name": "Race", **fields})
        session.add(event)
        session.commit()
        return event.id


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("45:00", 2700), ("1:45:00", 6300), (" 0:59 ", 59), ("90:00", 5400), ("100:00:00", 360_000)],
)
def test_a_target_time_is_read_as_hours_minutes_and_seconds(text: str, seconds: int) -> None:
    assert goals.parse_time(text) == seconds


# The last one is 3:00 with a digit of another script.
@pytest.mark.parametrize(
    "text", ["", "90", "1:60", "1:75:00", "0:00", "an hour", "1:2:3", chr(0x663) + ":00"]
)
def test_a_target_time_that_is_not_one_is_refused(text: str) -> None:
    with pytest.raises(GoalError):
        goals.parse_time(text)


def test_a_number_may_have_a_comma_and_must_be_in_range() -> None:
    assert goals.parse_number(" 21,1 ", "the distance", 100) == 21.1
    for text in ("", "far", "nan", "inf", "-1", "0", "101"):
        with pytest.raises(GoalError):
            goals.parse_number(text, "the distance", 100)


def test_a_sport_covers_the_kinds_garmin_tells_apart() -> None:
    assert goals.is_sport("trail_running", "running")
    assert goals.is_sport("virtual_ride", "cycling")
    assert goals.is_sport("lap_swimming", "swimming")
    assert not goals.is_sport("hiking", "cycling")
    assert not goals.is_sport("motorcycling", "cycling")
    assert goals.is_sport("motorcycling", None)
    assert not goals.is_sport(None, "running")
    assert goals.is_sport(None, None)


def test_weekly_progress_counts_this_week_and_the_weeks_before(db: Engine, user: User) -> None:
    add_activities(
        db,
        user,
        [
            # This week, from Monday the 28th.
            (2, "trail_running", 1, 10),
            (0, "running", 0.5, 5.5),
            (1, "cycling", 2, 50),
            # Its legs count, the whole does not.
            (0, "multi_sport", 5, 80),
            # Last week.
            (3, "running", 2, 21),
            # Eight weeks back, the first one looked at, and the Sunday before it.
            (58, "treadmill_running", 2.5, None),
            (59, "running", 9, 90),
        ],
    )
    add_activities(db, make_user(db, OTHER_EMAIL), [(0, "running", 8, 80)])
    add_weekly_goal(db, user, Measure.HOURS, 2, "running")
    add_weekly_goal(db, user, Measure.DISTANCE, 60)
    add_weekly_goal(db, user, Measure.ACTIVITIES, 3)

    with Session(db) as session:
        hours, distance, count = goals.weekly_progress(session, user.id, TODAY)

    assert (hours.value, hours.met, hours.share) == (1.5, False, 75)
    assert hours.weeks_met == [True, False, False, False, False, False, False, True]
    assert (hours.title, hours.done) == ("2 hours of running a week", "1.5 h")
    assert (distance.value, distance.met, distance.share) == (65.5, True, 100)
    assert (distance.weeks_reached, distance.title) == (0, "60 km a week")
    assert (count.value, count.done, count.met) == (3, "3", True)
    assert count.title == "3 activities a week"


def test_weekly_progress_of_a_user_without_goals_is_empty(db: Engine, user: User) -> None:
    add_weekly_goal(db, make_user(db, OTHER_EMAIL), Measure.HOURS, 2)

    with Session(db) as session:
        assert goals.weekly_progress(session, user.id, TODAY) == []


def test_garmins_prediction_is_given_for_a_run_of_a_distance_it_predicts(
    db: Engine, user: User
) -> None:
    with Session(db) as session:
        session.add_all(
            [
                RacePrediction(
                    user_id=user.id, calendar_date=days_ago(9), time_half_marathon_s=6500
                ),
                RacePrediction(
                    user_id=user.id, calendar_date=days_ago(2), time_half_marathon_s=6430
                ),
                RacePrediction(user_id=user.id, calendar_date=days_ago(1), time_5k_s=1380),
            ]
        )
        session.commit()

        def predicted(sport: str | None, km: float | None) -> int | None:
            event = GoalEvent(sport=sport, distance_m=None if km is None else km * 1000)
            return goals.predicted_time(session, user.id, event)

        assert predicted("running", 21.1) == 6430
        assert predicted("running", 5) == 1380
        assert predicted("running", 10) is None
        assert predicted("running", 15) is None
        assert predicted("running", None) is None
        assert predicted("cycling", 42.195) is None


def test_events_to_come_and_past_events_with_the_activity_of_the_day(
    db: Engine, user: User
) -> None:
    add_activities(
        db,
        user,
        [(10, "running", 0.2, 2), (10, "trail_running", 1.8, 21.3), (10, "cycling", 3, 90)],
    )
    add_event(db, user, days_ago(10), sport="running", distance_m=21_100, target_time_s=6300)
    add_event(db, user, TODAY)
    add_event(db, user, TODAY + timedelta(days=1))
    add_event(db, user, TODAY + timedelta(days=13))
    add_event(db, user, TODAY + timedelta(days=30), distance_m=10_000, target_time_s=2500)
    add_event(db, make_user(db, OTHER_EMAIL), TODAY + timedelta(days=2))

    with Session(db) as session:
        upcoming = goals.upcoming_events(session, user.id, TODAY)
        (past,) = goals.past_events(session, user.id, TODAY)
        soonest = goals.upcoming_events(session, user.id, TODAY, limit=1)

    assert [view.countdown for view in upcoming] == [
        "Today",
        "Tomorrow",
        "In 13 days",
        "In 4 weeks",
    ]
    assert upcoming[3].target_speed_mps == 4
    assert upcoming[0].target_speed_mps is None
    assert [view.days_to_go for view in soonest] == [0]
    assert past.days_to_go == -10
    assert past.result is not None
    assert past.result.type_key == "trail_running"


def test_goals_page_shows_weekly_goals_and_events(
    client: TestClient, db: Engine, user: User
) -> None:
    add_activities(db, user, [(1, "running", 1.5, 15), (10, "running", 1.7, 21.1)])
    with Session(db) as session:
        session.add(
            RacePrediction(user_id=user.id, calendar_date=days_ago(1), time_half_marathon_s=6430)
        )
        session.commit()
    add_event(db, user, days_ago(10), sport="running")

    assert client.post("/goals/events/new", data=HALF_MARATHON).headers["location"] == "/goals"
    weekly = {"measure": "hours", "target": "1,5", "sport": "running"}
    assert client.post("/goals/weekly/new", data=weekly).status_code == 303
    page = client.get("/goals").text

    assert "Dune half" in page
    assert "In 3 weeks" in page
    assert "25 Oct 2026" in page
    assert "· Running · 21.1 km · target 1:45:00 (4:59 /km)" in page
    assert "Garmin predicts 1:47:10" in page
    assert "2:10 slower</span> than your target." in page
    assert "1.5 hours of running a week" in page
    assert "1.5 h this week" in page
    assert "Reached</span>" in page
    assert 'value="100" max="100"' in page
    assert "Reached in 1 of the 8 weeks before" in page
    assert "Past events" in page
    assert 'href="/activities/2"' in page
    assert "21.1 km in 1:42:00" in page
    assert 'aria-current="page">Goals' in page


def test_goals_page_without_goals_says_so(client: TestClient) -> None:
    page = client.get("/goals").text

    assert "No weekly goals yet" in page
    assert "No events to come" in page
    assert "Past events" not in page


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"name": "  "}, "Give the event a name."),
        ({"day": "soon"}, "Pick the date of the event."),
        ({"day": "1999-12-31"}, "The date must be between 2000 and 2100."),
        ({"sport": "chess"}, "Pick a sport from the list."),
        ({"distance": "far"}, "The distance is not a number."),
        ({"distance": "0"}, "The distance must be more than 0 and at most 10000."),
        ({"target_time": "fast"}, "Write the target time as h:mm:ss or mm:ss."),
    ],
)
def test_an_event_that_cannot_be_used_comes_back_with_what_was_entered(
    client: TestClient, db: Engine, change: dict[str, str], message: str
) -> None:
    response = client.post("/goals/events/new", data=HALF_MARATHON | change)

    assert response.status_code == 400
    assert message in response.text
    assert '<option value="running" selected>' in response.text or "sport" in change
    assert 'value="2026-10-25"' in response.text or "day" in change
    with Session(db) as session:
        assert session.scalar(select(func.count()).select_from(GoalEvent)) == 0


def test_an_event_needs_only_a_name_and_a_date_and_its_name_is_shown_as_text(
    client: TestClient,
) -> None:
    response = client.post("/goals/events/new", data={"name": "<b>Tour</b>", "day": "2026-09-30"})
    page = client.get("/goals").text

    assert response.status_code == 303
    assert "&lt;b&gt;Tour&lt;/b&gt;" in page
    assert "<b>Tour</b>" not in page
    assert "Garmin predicts" not in page


def test_an_event_can_be_changed_and_removed(client: TestClient, db: Engine, user: User) -> None:
    event_id = add_event(db, user, TODAY, sport="cycling", distance_m=120_000, target_time_s=16_200)

    form = client.get(f"/goals/events/{event_id}").text
    assert 'value="Race"' in form
    assert 'value="120"' in form
    assert 'value="4:30:00"' in form
    assert '<option value="cycling" selected>' in form
    assert f'action="/goals/events/{event_id}/remove"' in form

    refused = client.post(f"/goals/events/{event_id}", data=HALF_MARATHON | {"name": ""})
    assert refused.status_code == 400
    changed = client.post(f"/goals/events/{event_id}", data=HALF_MARATHON | {"distance": ""})
    assert changed.status_code == 303
    with Session(db) as session:
        event = session.get_one(GoalEvent, event_id)
        assert (event.name, event.event_date, event.sport) == (
            "Dune half",
            date(2026, 10, 25),
            "running",
        )
        assert (event.distance_m, event.target_time_s) == (None, 6300)

    assert client.post(f"/goals/events/{event_id}/remove").headers["location"] == "/goals"
    with Session(db) as session:
        assert session.get(GoalEvent, event_id) is None


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"measure": "steps", "target": "3"}, "Pick what to count."),
        ({"measure": "hours", "target": ""}, "The target is not a number."),
        ({"measure": "hours", "target": "101"}, "The target must be more than 0 and at most 100."),
        ({"measure": "activities", "target": "2.5"}, "A number of activities is a whole number."),
        ({"measure": "distance", "target": "40", "sport": "chess"}, "Pick a sport from the list."),
        ({"measure": "hours", "target": "0.04"}, "The target must be at least 0.1."),
        ({}, "Pick what to count."),
    ],
)
def test_a_weekly_goal_that_cannot_be_used_is_refused(
    client: TestClient, db: Engine, data: dict[str, str], message: str
) -> None:
    response = client.post("/goals/weekly/new", data=data)

    assert response.status_code == 400
    assert message in response.text
    with Session(db) as session:
        assert session.scalar(select(func.count()).select_from(WeeklyGoal)) == 0


def test_a_weekly_goal_can_be_changed_and_removed(
    client: TestClient, db: Engine, user: User
) -> None:
    goal_id = add_weekly_goal(db, user, Measure.DISTANCE, 40, "running")

    form = client.get(f"/goals/weekly/{goal_id}").text
    assert '<option value="distance" selected>' in form
    assert 'value="40"' in form
    assert '<option value="running" selected>' in form

    # A target has one decimal, as the sum of a week has.
    assert client.post(f"/goals/weekly/{goal_id}", data={"measure": "hours", "target": "2.25"})
    with Session(db) as session:
        assert session.get_one(WeeklyGoal, goal_id).target == 2.2
    data = {"measure": "activities", "target": "1", "sport": ""}
    assert client.post(f"/goals/weekly/{goal_id}", data=data).status_code == 303
    assert "1 activity a week" in client.get("/goals").text
    refused = client.post(f"/goals/weekly/{goal_id}", data={"measure": "hours", "target": "x"})
    assert refused.status_code == 400
    with Session(db) as session:
        goal = session.get_one(WeeklyGoal, goal_id)
        assert (goal.measure, goal.target, goal.sport) == (Measure.ACTIVITIES, 1, None)

    assert client.post(f"/goals/weekly/{goal_id}/remove").status_code == 303
    with Session(db) as session:
        assert session.get(WeeklyGoal, goal_id) is None


def test_a_goal_of_someone_else_does_not_exist(client: TestClient, db: Engine) -> None:
    other = make_user(db, OTHER_EMAIL)
    event_id = add_event(db, other, TODAY + timedelta(days=5))
    goal_id = add_weekly_goal(db, other, Measure.HOURS, 5)
    weekly = {"measure": "hours", "target": "1"}

    assert "Race" not in client.get("/goals").text
    assert client.get(f"/goals/events/{event_id}").status_code == 404
    assert client.post(f"/goals/events/{event_id}", data=HALF_MARATHON).status_code == 404
    assert client.post(f"/goals/events/{event_id}/remove").status_code == 404
    assert client.get(f"/goals/weekly/{goal_id}").status_code == 404
    assert client.post(f"/goals/weekly/{goal_id}", data=weekly).status_code == 404
    assert client.post(f"/goals/weekly/{goal_id}/remove").status_code == 404
    assert client.get("/goals/events/not-an-id").status_code == 422
    with Session(db) as session:
        assert session.get_one(GoalEvent, event_id).name == "Race"
        assert session.get_one(WeeklyGoal, goal_id).target == 5


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/goals"),
        ("GET", "/goals/events/new"),
        ("POST", "/goals/events/new"),
        ("GET", "/goals/weekly/new"),
        ("POST", "/goals/weekly/new"),
        ("POST", f"/goals/events/{uuid.uuid4()}/remove"),
        ("POST", f"/goals/weekly/{uuid.uuid4()}/remove"),
    ],
)
def test_goals_need_a_signed_in_user(db: Engine, method: str, path: str) -> None:
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as anonymous:
        response = anonymous.request(method, path)

    assert (response.status_code, response.headers["location"]) == (303, "/login")


def test_there_is_a_most_to_the_goals_of_a_user(
    client: TestClient, db: Engine, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(goals, "MAX_GOALS", 1)
    add_event(db, user, TODAY)
    add_weekly_goal(db, user, Measure.HOURS, 5)

    event = client.post("/goals/events/new", data=HALF_MARATHON)
    weekly = client.post("/goals/weekly/new", data={"measure": "hours", "target": "1"})

    assert (event.status_code, weekly.status_code) == (400, 400)
    assert "You have 1 of these, which is the most; remove one first." in event.text


def test_overview_shows_the_goals_when_there_are_any(
    client: TestClient, db: Engine, user: User
) -> None:
    assert "All goals" not in client.get("/").text

    add_weekly_goal(db, user, Measure.ACTIVITIES, 3, "strength")
    for days in (40, 2, 9, 20):
        add_event(db, user, TODAY + timedelta(days=days), name=f"In {days}")
    page = client.get("/").text

    assert "All goals" in page
    assert "3 strength activities a week" in page
    assert "0 this week" in page
    # The three that come first.
    assert page.index("In 2<") < page.index("In 9<") < page.index("In 20<")
    assert "In 40<" not in page


def test_removing_a_user_removes_their_goals(db: Engine, user: User) -> None:
    add_event(db, user, TODAY)
    add_weekly_goal(db, user, Measure.HOURS, 5)

    with Session(db) as session:
        session.delete(session.get_one(User, user.id))
        session.commit()
        assert session.scalar(select(func.count()).select_from(GoalEvent)) == 0
        assert session.scalar(select(func.count()).select_from(WeeklyGoal)) == 0


def test_the_forms_for_a_new_goal_are_empty(client: TestClient) -> None:
    event = client.get("/goals/events/new").text
    weekly = client.get("/goals/weekly/new").text

    assert 'action="/goals/events/new"' in event
    assert 'action="/goals/weekly/new"' in weekly
    assert "selected" not in event + weekly
    assert "Remove this" not in event + weekly
