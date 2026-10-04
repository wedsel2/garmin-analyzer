"""Tests for the list of activities, the page of one, and the samples it reads."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from garmin_analyzer import activities
from garmin_analyzer.models import Activity, ActivityLap, ActivityZone, RawPayload, User
from garmin_analyzer.tokens import TokenCipher, generate_key
from garmin_analyzer.users import add_user, set_password
from garmin_analyzer.web.activity_pages import tempo
from garmin_analyzer.web.app import create_app

EMAIL = "runner@example.com"
OTHER_EMAIL = "other@example.com"
PASSWORD = "correct horse battery"  # noqa: S105
CIPHER = TokenCipher(generate_key())
START = datetime(2026, 9, 30, 7, tzinfo=UTC)
FIXTURE = Path(__file__).parent / "fixtures" / "garmin" / "activity_details.json"


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
def client(db: Engine, user: User) -> Iterator[TestClient]:
    """A browser signed in as the user."""
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as client:
        client.post("/login", data={"email": EMAIL, "password": PASSWORD})
        yield client


def add_activity(db: Engine, user: User, activity_id: int, **fields: Any) -> None:
    values = {"start_at": START - timedelta(days=activity_id), "type_key": "running"} | fields
    with Session(db) as session:
        session.add(Activity(user_id=user.id, activity_id=activity_id, **values))
        session.commit()


def details(keys: list[str], rows: list[list[Any]], **more: Any) -> dict[str, Any]:
    """A details response as Garmin gives it, with these metrics in this order."""
    return {
        "metricDescriptors": [{"metricsIndex": at, "key": key} for at, key in enumerate(keys)],
        "activityDetailMetrics": [{"metrics": row} for row in rows],
        **more,
    }


def add_details(db: Engine, user: User, activity_id: int, payload: Any) -> None:
    with Session(db) as session:
        session.add(
            RawPayload(
                user_id=user.id,
                endpoint="activity_details",
                resource_key=str(activity_id),
                payload=payload,
            )
        )
        session.commit()


def test_samples_are_read_by_the_name_of_the_metric() -> None:
    payload = details(
        ["directSpeed", "sumElapsedDuration", "directHeartRate", "directElevation", "directPower"],
        [
            [2.5, 0.0, 120, -1.5, -1],
            [3.0, 1.0, None, -2.0, -1],
            [-1, 2.0, 124, 0.5, -1],
        ],
    )

    samples = activities.samples_from(payload)

    assert samples == activities.Samples(
        seconds=[0, 1, 2],
        # Speed in km/h; a negative marker is no value, except for height; power was never measured.
        series={
            "speed": [9, 10.8, None],
            "heart_rate": [120, None, 124],
            "elevation": [-1.5, -2, 0.5],
        },
        route=[],
    )


def test_long_series_are_averaged_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(activities, "MAX_SAMPLES", 2)
    payload = details(
        ["sumDuration", "directDoubleCadence"],
        [[0.0, 160], [1.0, 170], [2.0, None], [3.0, 180], [4.0, 190]],
    )

    samples = activities.samples_from(payload)

    assert samples is not None
    assert (samples.seconds, samples.series) == ([0, 3], {"cadence": [165, 185]})


def test_route_comes_from_the_samples_or_else_from_the_polyline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(activities, "MAX_ROUTE_POINTS", 2)
    from_samples = details(
        ["directLatitude", "directLongitude"],
        [[52.0, 5.0], [None, None], [0.0, 0.0], [52.1, 5.1], [52.2, 5.2], [52.3, 5.3]],
    )
    from_polyline = details(
        ["directHeartRate"],
        [[100]],
        geoPolylineDTO={"polyline": [{"lat": 52.0, "lon": 5.0}, {"lat": None, "lon": None}]},
    )

    thinned = activities.samples_from(from_samples)
    polyline = activities.samples_from(from_polyline)

    # Longitude first; positions that are missing or zeroed are left out.
    assert thinned is not None
    assert thinned.route == [(5.0, 52.0), (5.2, 52.2)]
    assert polyline is not None
    assert polyline.route == [(5.0, 52.0)]


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"activityDetailMetrics": []}, {"activityDetailMetrics": [1, {"metrics": 2}]}],
)
def test_a_response_without_samples_gives_nothing(payload: Any) -> None:
    assert activities.samples_from(payload) is None


def test_the_synthetic_fixture_is_understood() -> None:
    samples = activities.samples_from(json.loads(FIXTURE.read_text(encoding="utf-8")))

    assert samples is not None
    assert len(samples.seconds) == 5
    assert set(samples.series) == {"speed"}
    # Made-up positions, as every number in the fixture is.
    assert len(samples.route) == 5


def test_tempo_is_pace_for_runners_and_speed_for_others() -> None:
    assert tempo("trail_running", 2.5) == "6:40 /km"
    assert tempo("cycling", 7.5) == "27.0 km/h"
    assert tempo("running", None) == tempo("running", 0) == ""


def test_api_gives_samples_of_an_own_activity_only(
    client: TestClient, db: Engine, user: User
) -> None:
    payload = details(["sumElapsedDuration", "directHeartRate"], [[0.0, 120], [5.0, 125]])
    add_activity(db, user, 1)
    add_details(db, user, 1, payload)
    other = make_user(db, OTHER_EMAIL)
    add_activity(db, other, 2)
    add_details(db, other, 2, payload)
    add_activity(db, user, 3)

    assert client.get("/api/v1/activities/1/samples").json() == {
        "seconds": [0, 5],
        "series": {"heart_rate": [120, 125]},
        "route": [],
    }
    # Someone else's, one without details, and one that does not exist.
    for activity_id in (2, 3, 99):
        assert client.get(f"/api/v1/activities/{activity_id}/samples").status_code == 404
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as anonymous:
        assert anonymous.get("/api/v1/activities/1/samples").status_code == 401


def test_list_shows_own_whole_activities_newest_first(
    client: TestClient, db: Engine, user: User
) -> None:
    add_activity(
        db,
        user,
        1,
        name="<b>Dunes</b>",
        type_key="trail_running",
        distance_m=12_345,
        duration_s=4_000,
        avg_speed_mps=3.0,
        avg_hr=148,
        training_load=120,
    )
    add_activity(db, user, 2, name="Polder loop", type_key="cycling", avg_speed_mps=7.5)
    add_activity(db, user, 3, name="Triathlon", type_key="multi_sport", is_parent=True)
    add_activity(db, make_user(db, OTHER_EMAIL), 4, name="Not mine")

    page = client.get("/activities").text

    assert page.index("&lt;b&gt;Dunes&lt;/b&gt;") < page.index("Polder loop")
    assert 'href="/activities/1"' in page
    for text in ("Trail running", "12.3 km", "1:06:40", "5:33 /km", "148 bpm", "27.0 km/h"):
        assert text in page
    assert "Triathlon" not in page
    assert "Not mine" not in page
    assert '<option value="cycling" >Cycling</option>' in page
    assert "multi_sport" not in page
    assert 'aria-label="Pages"' not in page
    assert 'aria-current="page">Activities' in page


def test_list_filters_by_sport_and_pages(
    client: TestClient, db: Engine, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(activities, "PAGE_SIZE", 2)
    for activity_id in range(1, 6):
        add_activity(db, user, activity_id, name=f"Run {activity_id}")
    add_activity(db, user, 6, name="Ride", type_key="cycling")

    second = client.get("/activities", params={"sport": "running", "page": 2}).text
    unknown = client.get("/activities", params={"sport": "curling"}).text

    assert "Run 3" in second
    assert "Run 4" in second
    assert "Run 2" not in second
    assert "Ride" not in second
    assert "Page 2 of 3" in second
    assert 'href="/activities?sport=running&amp;page=1">Newer' in second
    assert 'href="/activities?sport=running&amp;page=3">Older' in second
    assert '<option value="running" selected>' in second
    # A sport there are no activities of is no filter.
    assert "Page 1 of 3" in unknown
    assert client.get("/activities", params={"page": 0}).status_code == 422


def test_an_empty_list_says_so(client: TestClient) -> None:
    page = client.get("/activities").text

    assert "No activities collected yet." in page
    assert "<select" not in page


def test_detail_shows_figures_charts_zones_and_laps(
    client: TestClient, db: Engine, user: User
) -> None:
    add_activity(
        db,
        user,
        1,
        name="Dunes",
        type_key="trail_running",
        distance_m=10_000,
        duration_s=3_000,
        moving_duration_s=2_900,
        avg_speed_mps=10_000 / 3_000,
        avg_hr=148.4,
        elevation_gain_m=210,
        aerobic_training_effect=3.44,
        training_effect_label="AEROBIC_BASE",
        location_name="Schoorl",
    )
    add_details(db, user, 1, details(["directHeartRate"], [[120]]))
    with Session(db) as session:
        session.add_all(
            [
                ActivityLap(
                    user_id=user.id,
                    activity_id=1,
                    lap_index=0,
                    start_at=START,
                    distance_m=1000,
                    duration_s=300,
                    avg_speed_mps=1000 / 300,
                    avg_hr=140,
                ),
                ActivityZone(
                    user_id=user.id,
                    activity_id=1,
                    kind="hr",
                    zone_number=1,
                    seconds=600,
                    low_boundary=98,
                ),
                ActivityZone(
                    user_id=user.id,
                    activity_id=1,
                    kind="hr",
                    zone_number=2,
                    seconds=1800,
                    low_boundary=117,
                ),
                ActivityZone(
                    user_id=user.id, activity_id=1, kind="power", zone_number=1, seconds=0
                ),
            ]
        )
        session.commit()

    page = client.get("/activities/1").text

    for text in (
        "Dunes",
        "Trail running",
        "Schoorl",
        "10.0 km",
        "50:00",
        "48:20",
        "Average pace",
        "5:00 /km",
        "148 bpm",
        "210 m",
        "3.4",
        "Aerobic base",
    ):
        assert text in page
    assert "Average power" not in page
    assert 'data-chart="route" data-src="/api/v1/activities/1/samples"' in page
    assert page.count('data-chart="samples"') == 5
    assert 'data-metrics="speed" data-unit="km/h" data-hide-card\n           data-pace' in page
    assert "Time in heart rate zones" in page
    assert "from 117 bpm" in page
    assert "30:00 · 75%" in page
    # No time was spent in a power zone.
    assert "Time in power zones" not in page
    assert "<td>1</td>" in page
    assert 'aria-current="page">Activities' in page


def test_detail_without_a_recording_says_so(client: TestClient, db: Engine, user: User) -> None:
    add_activity(db, user, 1, name=None, type_key="strength_training", duration_s=1800)

    page = client.get("/activities/1").text

    assert "<h1" in page
    assert "Strength training" in page
    assert "Nothing was recorded through this activity." in page
    assert "data-chart" not in page
    assert "Laps" not in page


def test_someone_elses_activity_does_not_exist(client: TestClient, db: Engine) -> None:
    add_activity(db, make_user(db, OTHER_EMAIL), 7, name="Not mine")

    assert client.get("/activities/7").status_code == 404
    assert client.get("/activities/8").status_code == 404
    assert client.get("/activities/seven").status_code == 422
    # A number too large for the database is refused, not looked up.
    assert client.get(f"/activities/{2**63}").status_code == 422
    assert client.get(f"/api/v1/activities/{2**63}/samples").status_code == 422


def test_overview_links_to_activities_and_leaves_out_the_whole_of_a_multi_sport(
    client: TestClient, db: Engine, user: User
) -> None:
    from garmin_analyzer.models import GarminLink

    with Session(db) as session:
        session.add(GarminLink(user_id=user.id, encrypted_tokens=b"-"))
        session.commit()
    add_activity(db, user, 1, name="Swim leg", type_key="open_water_swimming")
    add_activity(db, user, 2, name="Triathlon", type_key="multi_sport", is_parent=True)

    page = client.get("/").text

    assert 'href="/activities/1"' in page
    assert 'href="/activities">All activities' in page
    assert "Triathlon" not in page
