"""Tests for the coach: what goes to Claude, who may ask, and the page.

Claude is replaced by a function of the test, so nothing leaves the machine.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from garmin_analyzer import claude, coach
from garmin_analyzer.claude import ClaudeError
from garmin_analyzer.coach import CoachError
from garmin_analyzer.db import make_session_factory
from garmin_analyzer.models import (
    Activity,
    CoachReport,
    CoachSettings,
    DailySummary,
    FitnessAge,
    GarminLink,
    GoalEvent,
    HrvSummary,
    Measure,
    RacePrediction,
    ReportStatus,
    SleepSession,
    TrainingReadiness,
    TrainingStatus,
    User,
    Vo2Max,
    WeeklyGoal,
)
from garmin_analyzer.tokens import TokenCipher, generate_key
from garmin_analyzer.users import add_user, set_password
from garmin_analyzer.web import coach_pages, shared
from garmin_analyzer.web.app import create_app

EMAIL = "runner@example.com"
OTHER_EMAIL = "other@example.com"
PASSWORD = "correct horse battery"  # noqa: S105
CIPHER = TokenCipher(generate_key())
INSTANCE_KEY = "sk-ant-of-the-instance"
OWN_KEY = "sk-ant-of-the-runner"
# A Wednesday.
TODAY = date(2026, 9, 30)
NOW = datetime(2026, 9, 30, 9, tzinfo=UTC)
REPORT = claude.Report(
    summary="You are in good shape for the Dune half.",
    recovery="Sleep is steady.\n\nHRV sits in your range.",
    training="Load is in the optimal range.",
    goals="Three runs a week: reached in most weeks.",
    week=[claude.PlannedDay(day="Thursday 1 October", session="Rest", reason="After intervals.")],
    watch=["Resting heart rate was up on Monday."],
)


class FakeClaude:
    """Stands in for claude.write_report and keeps what it was asked."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self.error: Exception | None = None

    def __call__(self, api_key: str, model: str, system: str, figures: str) -> claude.Written:
        self.calls.append((api_key, model, system, figures))
        if self.error is not None:
            raise self.error
        return claude.Written(REPORT, "claude-opus-5-5", 9000, 800)


def make_user(db: Engine, email: str) -> User:
    with Session(db, expire_on_commit=False) as session:
        user = add_user(session, email)
        user.name = "Robin Runner"
        session.flush()
        set_password(session, user, PASSWORD)
        session.add(GarminLink(user_id=user.id, encrypted_tokens=b"-"))
        session.commit()
        return user


def add_figures(db: Engine, user: User) -> None:
    """A day of everything the coach reads, a run and two goals."""
    with Session(db) as session:
        session.add_all(
            [
                DailySummary(
                    user_id=user.id,
                    calendar_date=TODAY,
                    resting_hr=47,
                    avg_stress=31,
                    body_battery_high=88,
                    body_battery_low=22,
                    steps=10432,
                ),
                SleepSession(
                    user_id=user.id,
                    calendar_date=TODAY,
                    start_at=NOW - timedelta(hours=10),
                    end_at=NOW - timedelta(hours=2),
                    sleep_s=27000,
                    score=83,
                ),
                HrvSummary(
                    user_id=user.id,
                    calendar_date=TODAY,
                    last_night_avg=61,
                    baseline_balanced_low=55,
                    baseline_balanced_upper=70,
                    status="BALANCED",
                ),
                TrainingStatus(
                    user_id=user.id,
                    calendar_date=TODAY,
                    status="PRODUCTIVE",
                    acute_load=412,
                    chronic_load=380,
                    acwr=1.1,
                    acwr_status="OPTIMAL",
                    load_balance="AEROBIC_LOW_SHORTAGE",
                ),
                TrainingReadiness(
                    user_id=user.id,
                    measured_at=NOW,
                    calendar_date=TODAY,
                    score=74,
                    level="HIGH",
                    sleep_factor_pct=80,
                ),
                Vo2Max(user_id=user.id, calendar_date=TODAY, running=52.0),
                RacePrediction(user_id=user.id, calendar_date=TODAY, time_half_marathon_s=6000),
                FitnessAge(
                    user_id=user.id, calendar_date=TODAY, fitness_age=31.5, chronological_age=38
                ),
                Activity(
                    user_id=user.id,
                    activity_id=1,
                    start_at=NOW - timedelta(days=2),
                    type_key="trail_running",
                    name="Lunch run with Sam",
                    location_name="Schoorl",
                    start_latitude=52.7,
                    start_longitude=4.69,
                    duration_s=3600,
                    distance_m=11200,
                    avg_hr=148,
                    training_load=96,
                ),
                WeeklyGoal(user_id=user.id, measure=Measure.ACTIVITIES, target=3, sport="running"),
                GoalEvent(
                    user_id=user.id,
                    name="Dune half",
                    event_date=TODAY + timedelta(days=25),
                    sport="running",
                    distance_m=21097.5,
                    target_time_s=6300,
                    note="Hilly, on sand.\nI want to finish strong.",
                ),
                GoalEvent(
                    user_id=user.id,
                    name="City 10 km",
                    event_date=TODAY - timedelta(days=2),
                    sport="running",
                ),
            ]
        )
        session.commit()


def enable(db: Engine, user: User, key: str | None = None) -> None:
    with Session(db) as session:
        session.add(
            CoachSettings(
                user_id=user.id,
                enabled_at=NOW,
                encrypted_api_key=CIPHER.encrypt(key) if key else None,
            )
        )
        session.commit()


def reports(db: Engine) -> list[CoachReport]:
    with Session(db) as session:
        return list(session.scalars(select(CoachReport).order_by(CoachReport.created_at)))


@pytest.fixture
def user(db: Engine) -> User:
    user = make_user(db, EMAIL)
    add_figures(db, user)
    return user


@pytest.fixture
def fake() -> FakeClaude:
    return FakeClaude()


@pytest.fixture
def config(fake: FakeClaude) -> coach.Config:
    return coach.Config(INSTANCE_KEY, "claude-opus-5-5", per_day=2, write=fake)


@pytest.fixture
def client(
    db: Engine, user: User, config: coach.Config, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A browser signed in as the user, on the day the tests are written for."""
    monkeypatch.setattr(coach_pages, "today", lambda: TODAY)
    monkeypatch.setattr(coach_pages, "now", lambda: NOW)
    monkeypatch.setattr(shared, "today", lambda: TODAY)
    with TestClient(create_app(db, CIPHER, config), follow_redirects=False) as client:
        client.post("/login", data={"email": EMAIL, "password": PASSWORD})
        yield client


def test_the_figures_hold_what_was_measured_and_the_goals(db: Engine, user: User) -> None:
    with Session(db) as session:
        text = coach.figures(session, user.id, TODAY)

    assert "Today is Wednesday 2026-09-30." in text
    assert "Day,Sleep score,Sleep (h),HRV last night (ms),Resting heart rate (bpm)" in text
    assert "Wed 2026-09-30,83,7.5,61,47,31,88,22,74,412,380,10432" in text
    # A day without anything keeps its place.
    assert "Tue 2026-09-29,,,,,,,,,,," in text
    assert "Garmin calls 55 to 70 ms balanced" in text
    assert "Training status on 2026-09-30: PRODUCTIVE; acute to chronic load 1.1 (OPTIMAL)" in text
    assert "mix of the load of 4 weeks: AEROBIC_LOW_SHORTAGE." in text
    assert "Load of 4 weeks per intensity" not in text
    assert "Training readiness on 2026-09-30: 74 (HIGH)" in text
    # Weeks without anything are left out: of the averages, and before the first activity.
    assert "## Average per week" not in text
    assert "Week from,Trail running\n2026-09-28,1" in text
    assert "Sleep last night 80" in text
    assert "VO2 max running: 52" in text
    assert "Predicted time for Half marathon: 1:40:00" in text
    assert "Age 38; fitness age 31.5." in text
    assert "Mon 2026-09-28 09:00,trail_running,60,11.2,148,96" in text
    assert "- 3 running activities a week: 1 so far this week" in text
    assert (
        '- "Dune half": on Sun 2026-10-25, 25 days to go, running, 21.0975 km, '
        "target time 1:45:00, Garmin now predicts 1:40:00." in text
    )
    assert "  Their note:\n  Hilly, on sand.\n  I want to finish strong." in text
    assert '- "City 10 km": on Mon 2026-09-28, running, done in 1:00:00 over 11.2 km.' in text


def test_a_result_without_a_time_says_only_that_it_was_done(db: Engine, user: User) -> None:
    with Session(db) as session:
        session.get_one(Activity, (user.id, 1)).duration_s = None
        session.commit()

        text = coach.figures(session, user.id, TODAY)

    assert '- "City 10 km": on Mon 2026-09-28, running, done over 11.2 km.' in text


def test_the_figures_say_nothing_of_who_or_where(db: Engine, user: User) -> None:
    with Session(db) as session:
        text = coach.figures(session, user.id, TODAY)

    for private in ("runner@example.com", "Robin", "Lunch run", "Sam", "Schoorl", "52.7", "4.69"):
        assert private not in text


def test_the_figures_of_someone_without_any_are_still_a_message(db: Engine) -> None:
    nobody = make_user(db, OTHER_EMAIL)

    with Session(db) as session:
        text = coach.figures(session, nobody.id, TODAY)

    assert "## Latest from Garmin\nNothing." in text
    assert "## Activities, the last 28 days\nNone." in text
    assert "They have set no goals." in text
    assert "## Hours of activities" not in text


def test_a_table_leaves_out_empty_columns_and_keeps_commas_out_of_values() -> None:
    assert (
        coach.table(["A", "B", "C"], [[1, None, "x,y"], [2.0, None, 3.25]]) == "A,C\n1,x;y\n2,3.2"
    )


def test_the_text_for_a_chat_holds_the_instructions_and_the_figures(
    client: TestClient, fake: FakeClaude
) -> None:
    assert 'href="/coach/figures"' in client.get("/coach").text

    page = client.get("/coach/figures").text

    assert '<script src="/static/coach.js" defer></script>' in page
    assert "data-copy" in client.get("/static/coach.js").text
    assert "I would like you to be my coach." in page
    assert "You are not a doctor" in page
    assert "Wed 2026-09-30,83,7.5,61,47" in page
    # Needs no coach turned on, and the app sends nothing.
    assert fake.calls == []
    for private in ("Robin", "Lunch run", "Schoorl"):
        assert private not in page


def test_the_text_for_a_chat_can_be_saved_as_a_file(
    client: TestClient, db: Engine, user: User
) -> None:
    file = client.get("/coach/figures.txt")

    assert file.headers["content-type"] == "text/plain; charset=utf-8"
    assert file.headers["content-disposition"] == 'attachment; filename="figures-2026-09-30.txt"'
    assert file.headers["cache-control"] == "no-store"
    with Session(db) as session:
        assert file.text == coach.for_chat(session, user.id, TODAY)
    assert file.text.startswith("I would like you to be my coach.")
    assert "- Write in English" not in file.text
    assert "No markdown" not in file.text


def test_the_text_for_a_chat_is_ones_own_and_needs_figures(db: Engine, user: User) -> None:
    make_user(db, OTHER_EMAIL)
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as other:
        assert other.get("/coach/figures").headers["location"] == "/login"
        assert other.get("/coach/figures.txt").headers["location"] == "/login"
        other.post("/login", data={"email": OTHER_EMAIL, "password": PASSWORD})

        page = other.get("/coach/figures")
        file = other.get("/coach/figures.txt")

    assert "Nothing has been collected from Garmin yet" in page.text
    assert "Dune half" not in page.text
    assert "<textarea" not in page.text
    assert file.status_code == 404


def test_the_instructions_for_a_report_and_for_a_chat_share_the_coaching() -> None:
    assert coach.SYSTEM.startswith(coach.COACHING)
    assert coach.COACHING in coach.CHAT
    assert "No markdown" in coach.SYSTEM


def test_nothing_is_sent_before_the_user_turns_the_coach_on(
    client: TestClient, db: Engine, fake: FakeClaude
) -> None:
    page = client.get("/coach")
    assert "let Claude read your figures here" in page.text
    assert "Write a new report" not in page.text

    refused = client.post("/coach/report")

    assert refused.status_code == 400
    assert "Turn the coach on first." in refused.text
    assert fake.calls == []
    assert reports(db) == []


def test_a_report_is_written_with_the_key_of_the_instance_and_shown(
    client: TestClient, db: Engine, fake: FakeClaude
) -> None:
    assert client.post("/coach/enable").headers["location"] == "/coach"

    assert client.post("/coach/report").headers["location"] == "/coach"

    [(key, model, system, figures)] = fake.calls
    assert (key, model, system) == (INSTANCE_KEY, "claude-opus-5-5", coach.SYSTEM)
    assert "Wed 2026-09-30,83" in figures
    [report] = reports(db)
    assert report.status is ReportStatus.DONE
    assert not report.own_key
    assert (report.model, report.input_tokens, report.output_tokens) == (
        "claude-opus-5-5",
        9000,
        800,
    )
    page = client.get("/coach").text
    assert "You are in good shape for the Dune half." in page
    assert "Thursday 1 October" in page
    assert "Resting heart rate was up on Monday." in page
    assert "1 of 2 left in these 24 hours." in page
    assert "hx-trigger" not in page


def test_the_key_of_the_instance_writes_only_so_many_reports_a_day(
    client: TestClient, db: Engine, fake: FakeClaude
) -> None:
    client.post("/coach/enable")
    client.post("/coach/report")
    client.post("/coach/report")

    refused = client.post("/coach/report")

    assert refused.status_code == 400
    assert "You have had 2 reports in the last 24 hours, which is the most." in refused.text
    assert len(fake.calls) == 2
    assert "0 of 2 left" in refused.text


def test_a_report_of_more_than_a_day_ago_no_longer_counts(
    client: TestClient, db: Engine, user: User, fake: FakeClaude
) -> None:
    enable(db, user)
    with Session(db) as session:
        for _ in range(2):
            session.add(
                CoachReport(
                    user_id=user.id,
                    status=ReportStatus.DONE,
                    content=REPORT.model_dump(),
                    created_at=NOW - timedelta(hours=25),
                )
            )
        session.commit()

    assert client.post("/coach/report").status_code == 303
    assert len(fake.calls) == 1


def test_a_key_of_ones_own_is_stored_encrypted_and_has_no_limit(
    client: TestClient, db: Engine, user: User, fake: FakeClaude
) -> None:
    client.post("/coach/enable")
    assert client.post("/coach/key", data={"api_key": f" {OWN_KEY} "}).status_code == 303

    for _ in range(3):
        assert client.post("/coach/report").status_code == 303

    assert [call[0] for call in fake.calls] == [OWN_KEY] * 3
    assert all(report.own_key for report in reports(db))
    with Session(db) as session:
        stored = session.get_one(CoachSettings, user.id).encrypted_api_key
    assert stored is not None
    assert OWN_KEY.encode() not in stored
    assert CIPHER.decrypt(stored) == OWN_KEY
    page = client.get("/coach").text
    assert "Reports are written with your own Anthropic API key" in page
    assert OWN_KEY not in page
    assert "left in these 24 hours" not in page


@pytest.mark.parametrize("key", ["", "hunter2", "sk-ant-" + "x" * 300, "sk-ant-é"])
def test_something_that_is_no_key_is_refused(client: TestClient, db: Engine, key: str) -> None:
    client.post("/coach/enable")

    refused = client.post("/coach/key", data={"api_key": key})

    assert refused.status_code == 400
    assert "An Anthropic API key starts with sk-ant-." in refused.text


def test_removing_the_key_goes_back_to_that_of_the_instance(
    client: TestClient, db: Engine, user: User, fake: FakeClaude
) -> None:
    enable(db, user, OWN_KEY)

    client.post("/coach/key/remove")
    client.post("/coach/report")

    assert fake.calls[0][0] == INSTANCE_KEY


def test_without_any_key_there_is_no_report(db: Engine, user: User, fake: FakeClaude) -> None:
    enable(db, user)
    with TestClient(create_app(db, CIPHER, coach.Config(write=fake))) as client:
        client.post("/login", data={"email": EMAIL, "password": PASSWORD})

        page = client.get("/coach")
        refused = client.post("/coach/report")

    assert "This instance has no API key. Enter your own below." in page.text
    assert refused.status_code == 400
    assert "There is no API key to ask Claude with; enter your own." in refused.text
    assert fake.calls == []


def test_a_key_that_can_no_longer_be_read_is_asked_for_again(
    client: TestClient, db: Engine, user: User, fake: FakeClaude
) -> None:
    with Session(db) as session:
        session.add(
            CoachSettings(
                user_id=user.id,
                enabled_at=NOW,
                encrypted_api_key=TokenCipher(generate_key()).encrypt(OWN_KEY),
            )
        )
        session.commit()

    refused = client.post("/coach/report")

    assert refused.status_code == 400
    assert "Your API key can no longer be read; enter it again." in refused.text
    assert fake.calls == []


def test_a_key_is_encrypted_again_when_the_encryption_key_is_replaced(
    db: Engine, user: User, config: coach.Config, fake: FakeClaude
) -> None:
    old = generate_key()
    with Session(db) as session:
        session.add(
            CoachSettings(
                user_id=user.id, enabled_at=NOW, encrypted_api_key=TokenCipher(old).encrypt(OWN_KEY)
            )
        )
        session.commit()
    new = generate_key()
    both = TokenCipher(f"{new},{old}")
    sessions = make_session_factory(db)

    with sessions() as session:
        report = coach.request_report(session, user.id, config, both, NOW)
    assert report is not None
    coach.write_pending(sessions, report.id, config, both, TODAY)

    assert fake.calls[0][0] == OWN_KEY
    with Session(db) as session:
        stored = session.get_one(CoachSettings, user.id).encrypted_api_key
    assert stored is not None
    assert TokenCipher(new).decrypt(stored) == OWN_KEY


def test_a_key_entered_while_a_report_waits_is_left_as_it_is(
    db: Engine, user: User, config: coach.Config, fake: FakeClaude
) -> None:
    enable(db, user)
    old = generate_key()
    both = TokenCipher(f"{generate_key()},{old}")
    sessions = make_session_factory(db)
    with sessions() as session:
        report = coach.request_report(session, user.id, config, both, NOW)
        assert report is not None
        session.get_one(CoachSettings, user.id).encrypted_api_key = TokenCipher(old).encrypt(
            OWN_KEY
        )
        session.commit()

    coach.write_pending(sessions, report.id, config, both, TODAY)

    # The report was started on the key of the instance and is written with it.
    assert fake.calls[0][0] == INSTANCE_KEY
    with Session(db) as session:
        stored = session.get_one(CoachSettings, user.id).encrypted_api_key
    assert stored is not None
    assert both.decrypt(stored) == OWN_KEY


def test_there_is_no_report_on_nothing(db: Engine, config: coach.Config, fake: FakeClaude) -> None:
    nobody = make_user(db, OTHER_EMAIL)
    enable(db, nobody)

    with (
        Session(db) as session,
        pytest.raises(CoachError, match="nothing has been collected from Garmin yet"),
    ):
        coach.request_report(session, nobody.id, config, CIPHER, NOW)


def test_what_claude_could_not_do_is_shown_and_does_not_count(
    client: TestClient, db: Engine, fake: FakeClaude
) -> None:
    client.post("/coach/enable")
    fake.error = ClaudeError("Anthropic does not accept the API key")

    client.post("/coach/report")

    [report] = reports(db)
    assert report.status is ReportStatus.FAILED
    assert report.content is None
    page = client.get("/coach").text
    assert "Anthropic does not accept the API key." in page
    assert "2 of 2 left in these 24 hours." in page


def test_an_answer_that_was_paid_for_counts_also_when_it_is_no_report(
    client: TestClient, db: Engine, fake: FakeClaude
) -> None:
    client.post("/coach/enable")
    fake.error = claude.Unusable("the answer of Claude could not be read")

    client.post("/coach/report")
    client.post("/coach/report")

    assert "0 of 2 left in these 24 hours." in client.get("/coach").text
    assert client.post("/coach/report").status_code == 400
    assert len(fake.calls) == 2


def test_turning_the_coach_on_twice_is_the_same_as_once(
    client: TestClient, db: Engine, user: User
) -> None:
    client.post("/coach/enable")
    with Session(db) as session:
        first = session.get_one(CoachSettings, user.id).enabled_at

    assert client.post("/coach/enable").status_code == 303

    with Session(db) as session:
        assert session.get_one(CoachSettings, user.id).enabled_at == first


def test_an_error_nobody_foresaw_fails_the_report_without_its_message(
    client: TestClient, db: Engine, fake: FakeClaude, caplog: pytest.LogCaptureFixture
) -> None:
    client.post("/coach/enable")
    fake.error = RuntimeError("resting heart rate 47")

    client.post("/coach/report")

    [report] = reports(db)
    assert report.error == "Something went wrong while writing the report."
    assert "writing a report failed: RuntimeError" in caplog.text
    assert "47" not in caplog.text


def test_one_report_at_a_time_and_the_page_asks_again_while_it_is_written(
    client: TestClient, db: Engine, user: User, fake: FakeClaude
) -> None:
    enable(db, user)
    with Session(db) as session:
        session.add(CoachReport(user_id=user.id, created_at=NOW - timedelta(minutes=1)))
        session.commit()

    assert client.post("/coach/report").status_code == 303

    assert fake.calls == []
    assert len(reports(db)) == 1
    page = client.get("/coach").text
    assert "Claude is writing your report." in page
    assert 'hx-get="/coach" hx-trigger="every 4s"' in page
    assert "disabled>Write a new report" in page


def test_a_report_that_never_came_is_given_up_on(
    client: TestClient, db: Engine, user: User, fake: FakeClaude
) -> None:
    enable(db, user)
    with Session(db) as session:
        session.add(CoachReport(user_id=user.id, created_at=NOW - timedelta(minutes=16)))
        session.commit()

    page = client.get("/coach").text

    assert "Writing the report took too long." in page
    assert "hx-trigger" not in page
    assert client.post("/coach/report").status_code == 303
    assert len(fake.calls) == 1


def test_a_report_that_was_removed_while_claude_wrote_stays_removed(
    db: Engine, user: User, config: coach.Config, fake: FakeClaude
) -> None:
    enable(db, user)
    sessions = make_session_factory(db)
    with sessions() as session:
        report = coach.request_report(session, user.id, config, CIPHER, NOW)
    assert report is not None

    def write_and_remove(api_key: str, model: str, system: str, figures: str) -> claude.Written:
        with sessions() as session:
            session.delete(session.get_one(CoachReport, report.id))
            session.commit()
        return fake(api_key, model, system, figures)

    slow = coach.Config(INSTANCE_KEY, write=write_and_remove)
    coach.write_pending(sessions, report.id, slow, CIPHER, TODAY)

    assert reports(db) == []
    # And one that is done is not written again.
    coach.write_pending(sessions, report.id, config, CIPHER, TODAY)
    assert len(fake.calls) == 1


def test_turning_the_coach_off_while_a_report_waits_sends_nothing(
    db: Engine, user: User, config: coach.Config, fake: FakeClaude
) -> None:
    enable(db, user)
    sessions = make_session_factory(db)
    with sessions() as session:
        report = coach.request_report(session, user.id, config, CIPHER, NOW)
        assert report is not None
        session.get_one(CoachSettings, user.id).enabled_at = None
        session.commit()

    coach.write_pending(sessions, report.id, config, CIPHER, TODAY)

    assert fake.calls == []
    assert reports(db)[0].error == "The coach was turned off."


def test_only_the_latest_reports_are_kept(
    db: Engine, user: User, config: coach.Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(coach, "REPORTS_KEPT", 2)
    enable(db, user, OWN_KEY)
    sessions = make_session_factory(db)

    for minutes in range(3):
        with sessions() as session:
            report = coach.request_report(
                session, user.id, config, CIPHER, NOW + timedelta(minutes=minutes)
            )
        assert report is not None
        coach.write_pending(sessions, report.id, config, CIPHER, TODAY)

    assert len(reports(db)) == 2


def test_an_earlier_report_can_be_read_and_that_of_someone_else_does_not_exist(
    client: TestClient, db: Engine, user: User
) -> None:
    other = make_user(db, OTHER_EMAIL)
    enable(db, user)
    with Session(db) as session:
        earlier = CoachReport(
            user_id=user.id,
            status=ReportStatus.DONE,
            content={**REPORT.model_dump(), "summary": "An earlier one."},
            created_at=NOW - timedelta(days=3),
        )
        latest = CoachReport(user_id=user.id, status=ReportStatus.DONE, content=REPORT.model_dump())
        theirs = CoachReport(
            user_id=other.id,
            status=ReportStatus.DONE,
            content={**REPORT.model_dump(), "summary": "Not yours."},
        )
        session.add_all([earlier, latest, theirs])
        session.commit()
        earlier_id, their_id = earlier.id, theirs.id

    assert "You are in good shape" in client.get("/coach").text
    assert "An earlier one." in client.get(f"/coach/reports/{earlier_id}").text
    assert client.get(f"/coach/reports/{their_id}").status_code == 404
    assert client.get(f"/coach/reports/{uuid.uuid4()}").status_code == 404
    assert "Not yours." not in client.get("/coach").text


def test_turning_off_keeps_the_reports_until_they_are_removed(
    client: TestClient, db: Engine, user: User, fake: FakeClaude
) -> None:
    other = make_user(db, OTHER_EMAIL)
    with Session(db) as session:
        session.add(CoachReport(user_id=other.id, status=ReportStatus.DONE, content={}))
        session.commit()
    client.post("/coach/enable")
    client.post("/coach/report")

    client.post("/coach/disable")

    page = client.get("/coach").text
    assert "let Claude read your figures here" in page
    assert "Reports written before you turned the coach off are still stored." in page
    assert client.post("/coach/report").status_code == 400
    assert len(fake.calls) == 1

    client.post("/coach/reports/remove")

    assert [report.user_id for report in reports(db)] == [other.id]


def test_what_claude_wrote_is_shown_as_text_not_as_markup(
    client: TestClient, db: Engine, user: User
) -> None:
    enable(db, user)
    with Session(db) as session:
        content = {**REPORT.model_dump(), "summary": "<script>alert(1)</script>"}
        session.add(CoachReport(user_id=user.id, status=ReportStatus.DONE, content=content))
        session.commit()

    page = client.get("/coach").text

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_the_coach_needs_a_signed_in_user(db: Engine, user: User) -> None:
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as anonymous:
        assert anonymous.get("/coach").headers["location"] == "/login"
        assert anonymous.post("/coach/report").headers["location"] == "/login"


def test_removing_a_user_removes_their_reports_and_key(db: Engine, user: User) -> None:
    enable(db, user, OWN_KEY)
    with Session(db) as session:
        session.add(CoachReport(user_id=user.id))
        session.commit()
        session.delete(session.get_one(User, user.id))
        session.commit()

        assert session.scalar(select(CoachSettings)) is None
    assert reports(db) == []
