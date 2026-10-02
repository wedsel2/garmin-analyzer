"""Fetch data from Garmin for one user, store it raw and normalise it.

A sync has three parts: account-wide data, one batch of calls per day, and
activities. Recent days are always fetched again, because Garmin keeps adding
to them; older days and activity details are fetched once. That makes a sync
resumable: after an interruption the next run continues where data is missing.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from garmin_analyzer.garmin import GarminError, GarminSession, RateLimited, RelinkRequired
from garmin_analyzer.links import mark_needs_relink, open_link, save_tokens
from garmin_analyzer.models import GarminLink, RawFile, RawPayload
from garmin_analyzer.normalise import normalise
from garmin_analyzer.tokens import TokenCipher

# Endpoint name -> library method. The name is what raw payloads are stored
# under and what normalise.py looks up.

# Called once per sync.
ACCOUNT_ENDPOINTS = {
    "user_profile": "get_user_profile",
    "userprofile_settings": "get_userprofile_settings",
    "devices": "get_devices",
    "device_last_used": "get_device_last_used",
    "primary_training_device": "get_primary_training_device",
    "heart_rate_zones": "get_heart_rate_zones",
    "power_zones": "get_power_zones",
    "personal_record": "get_personal_record",
    "race_predictions": "get_race_predictions",
    "lactate_threshold": "get_lactate_threshold",
    "cycling_ftp": "get_cycling_ftp",
    "training_plans": "get_training_plans",
    "goals": "get_goals",
}

# Called once per day, with the date.
DAILY_ENDPOINTS = {
    "user_summary": "get_user_summary",
    "sleep_data": "get_sleep_data",
    "heart_rates": "get_heart_rates",
    "stress_data": "get_stress_data",
    "respiration_data": "get_respiration_data",
    "hrv_data": "get_hrv_data",
    "steps_data": "get_steps_data",
    "spo2_data": "get_spo2_data",
    "floors": "get_floors",
    "intensity_minutes_data": "get_intensity_minutes_data",
    "hydration_data": "get_hydration_data",
    "all_day_events": "get_all_day_events",
    "body_battery_events": "get_body_battery_events",
    "training_readiness": "get_training_readiness",
    "training_status": "get_training_status",
    "fitnessage_data": "get_fitnessage_data",
    "daily_weigh_ins": "get_daily_weigh_ins",
    "lifestyle_logging_data": "get_lifestyle_logging_data",
}

# Called once per activity, with the activity id.
ACTIVITY_ENDPOINTS = {
    "activity": "get_activity",
    "activity_details": "get_activity_details",
    "activity_splits": "get_activity_splits",
    "activity_typed_splits": "get_activity_typed_splits",
    "activity_split_summaries": "get_activity_split_summaries",
    "activity_hr_in_timezones": "get_activity_hr_in_timezones",
    "activity_power_in_timezones": "get_activity_power_in_timezones",
    "activity_weather": "get_activity_weather",
    "activity_exercise_sets": "get_activity_exercise_sets",
}

ACTIVITY_FILE_KIND = "activity_original"
ACCOUNT_KEY = "-"
# Garmin still changes yesterday's data today (sleep, late device syncs).
REFETCH_DAYS = 2
DEFAULT_PAUSE_SECONDS = 1.0


@dataclass
class SyncResult:
    calls: int = 0
    rows: int = 0
    errors: list[str] = field(default_factory=list)
    # Set when the sync ended early; the next run picks up what is missing.
    stopped: str | None = None


class Collector:
    def __init__(
        self,
        session: Session,
        user_id: uuid.UUID,
        garmin: GarminSession,
        pause: float = DEFAULT_PAUSE_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session = session
        self.user_id = user_id
        self.garmin = garmin
        self.pause = pause
        self.sleep = sleep
        self.result = SyncResult()

    def sync(self, since: date, today: date) -> SyncResult:
        """Fetch what is new first, then fill in history, newest day first."""
        days = [today - timedelta(days=offset) for offset in range((today - since).days + 1)]
        self.sync_account()
        for day in days[:REFETCH_DAYS]:
            self.sync_day(day, refetch=True)
        self.sync_range(since, today)
        self.sync_activities(since, today)
        for day in days[REFETCH_DAYS:]:
            self.sync_day(day, refetch=False)
        return self.result

    def sync_account(self) -> None:
        for endpoint, method in ACCOUNT_ENDPOINTS.items():
            self.fetch(endpoint, ACCOUNT_KEY, method)
        self.session.commit()

    def sync_day(self, day: date, *, refetch: bool) -> None:
        key = day.isoformat()
        stored = set() if refetch else self.stored_endpoints(key)
        for endpoint, method in DAILY_ENDPOINTS.items():
            if endpoint not in stored:
                self.fetch(endpoint, key, method, key, day=day)
        self.session.commit()

    def sync_range(self, since: date, today: date) -> None:
        """Metrics Garmin only returns properly for a range of days."""
        start, end = since.isoformat(), today.isoformat()
        self.fetch("max_metrics", f"{start}..{end}", "get_max_metrics_range", start, end, day=today)
        self.session.commit()

    def sync_activities(self, since: date, today: date) -> None:
        activities = self.call(
            "activities", "get_activities_by_date", since.isoformat(), today.isoformat()
        )
        for summary in activities or []:
            activity_id = str(summary.get("activityId") or "")
            if not activity_id:
                continue
            self.store("activity_summary", activity_id, summary)
            stored = self.stored_endpoints(activity_id)
            for endpoint, method in ACTIVITY_ENDPOINTS.items():
                if endpoint not in stored:
                    self.fetch(endpoint, activity_id, method, activity_id)
            if not self.has_file(activity_id):
                self.fetch_file(activity_id)
            self.session.commit()

    def call(self, endpoint: str, method: str, *args: Any) -> Any:
        """One paced request. A failed request is recorded and returns None."""
        self.sleep(self.pause)
        self.result.calls += 1
        try:
            return self.garmin.call(method, *args)
        except RelinkRequired, RateLimited:
            raise
        except GarminError as error:
            self.result.errors.append(f"{endpoint} {' '.join(map(str, args))}: {error}")
            return None

    def fetch(
        self, endpoint: str, key: str, method: str, *args: Any, day: date | None = None
    ) -> None:
        errors_before = len(self.result.errors)
        payload = self.call(endpoint, method, *args)
        # An empty answer is stored too, so the day is not asked for again;
        # a failed request is not, so the next sync retries it.
        if len(self.result.errors) == errors_before:
            self.store(endpoint, key, payload, day)

    def store(self, endpoint: str, key: str, payload: Any, day: date | None = None) -> None:
        values = {
            "user_id": self.user_id,
            "endpoint": endpoint,
            "resource_key": key,
            "calendar_date": day,
            "payload": payload,
            "fetched_at": datetime.now(UTC),
        }
        statement = insert(RawPayload).values(values)
        self.session.execute(
            statement.on_conflict_do_update(
                constraint="uq_raw_payloads_user_id_endpoint_resource_key",
                set_={name: statement.excluded[name] for name in ("payload", "fetched_at")},
            )
        )
        # The raw answer is kept even when it cannot be normalised: an unexpected
        # shape must not stop the sync or lose data. It can be parsed again once
        # the parser is fixed.
        try:
            with self.session.begin_nested():
                self.result.rows += normalise(self.session, self.user_id, endpoint, payload, key)
        except Exception as error:
            self.result.errors.append(
                f"{endpoint} {key}: stored but not normalised: {type(error).__name__}: {error}"
            )

    def fetch_file(self, activity_id: str) -> None:
        self.sleep(self.pause)
        self.result.calls += 1
        try:
            content = self.garmin.download_original(activity_id)
        except RelinkRequired, RateLimited:
            raise
        except GarminError as error:
            self.result.errors.append(f"{ACTIVITY_FILE_KIND} {activity_id}: {error}")
            return
        self.session.add(
            RawFile(
                user_id=self.user_id,
                kind=ACTIVITY_FILE_KIND,
                resource_key=activity_id,
                content=content,
            )
        )

    def stored_endpoints(self, key: str) -> set[str]:
        """The endpoints already stored for a day or an activity."""
        return set(
            self.session.scalars(
                select(RawPayload.endpoint).where(
                    RawPayload.user_id == self.user_id, RawPayload.resource_key == key
                )
            )
        )

    def has_file(self, activity_id: str) -> bool:
        return (
            self.session.scalar(
                select(RawFile.id).where(
                    RawFile.user_id == self.user_id,
                    RawFile.kind == ACTIVITY_FILE_KIND,
                    RawFile.resource_key == activity_id,
                )
            )
            is not None
        )


def collect_user(
    session: Session,
    user_id: uuid.UUID,
    cipher: TokenCipher,
    since: date,
    today: date,
    pause: float = DEFAULT_PAUSE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> SyncResult:
    """Sync one user. Raises NotLinked or RelinkRequired when no session can be opened."""
    try:
        garmin = open_link(session, user_id, cipher)
    finally:
        # Keeps the refreshed tokens, or the mark that a new sign-in is needed.
        session.commit()
    collector = Collector(session, user_id, garmin, pause, sleep)
    try:
        collector.sync(since, today)
    except RelinkRequired as error:
        mark_needs_relink(session, user_id, str(error))
        collector.result.stopped = "Garmin rejected the tokens; link the account again"
    except RateLimited:
        collector.result.stopped = "Garmin rate limit reached; try again later"
    except Exception:
        session.rollback()
        raise
    else:
        session.get_one(GarminLink, user_id).last_synced_at = datetime.now(UTC)
    finally:
        # A refresh during the sync may have replaced the tokens. Losing them
        # would force a new sign-in, so they are saved however the sync ended.
        # What was fetched before an early stop is kept; the next sync skips it.
        save_tokens(session, user_id, cipher, garmin)
        session.commit()
    return collector.result
