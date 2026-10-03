"""Database schema.

Every table that holds user data has a user_id that cascades on delete, so
removing a user removes their data. Schema changes need an Alembic migration.
"""

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    MetaData,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit constraint names keep migrations deterministic.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid7)
    # Stored lower-cased by the application.
    email: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebSession(Base):
    """A signed-in browser. The cookie holds a random token; only its hash is stored."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PasswordLink(Base):
    """A link with which a user sets their password: an invite or a reset. One per user."""

    __tablename__ = "password_links"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LinkStatus(enum.Enum):
    ACTIVE = "active"
    NEEDS_RELINK = "needs_relink"


class GarminLink(Base):
    """The connection between a user and their Garmin account. At most one per user."""

    __tablename__ = "garmin_links"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Garmin tokens as JSON, encrypted with TOKEN_ENCRYPTION_KEY. Never plaintext.
    encrypted_tokens: Mapped[bytes] = mapped_column(LargeBinary)
    # Garmin's number for the account the data comes from, set by the first
    # sync. Tokens of another account are refused. See ADR 13.
    garmin_account_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[LinkStatus] = mapped_column(
        Enum(LinkStatus, name="link_status", values_callable=lambda e: [m.value for m in e]),
        default=LinkStatus.ACTIVE,
    )
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the last weekly catch-up over the previous two weeks completed.
    last_catch_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class RawPayload(Base):
    """One Garmin response, stored unchanged.

    resource_key identifies what was fetched within an endpoint: an ISO date for
    daily data, an activity id for activity data, or "-" for account-wide data.
    Fetching the same resource again replaces the row.
    """

    __tablename__ = "raw_payloads"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "endpoint",
            "resource_key",
            name="uq_raw_payloads_user_id_endpoint_resource_key",
        ),
        Index(
            "ix_raw_payloads_user_id_endpoint_calendar_date",
            "user_id",
            "endpoint",
            "calendar_date",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(Text)
    resource_key: Mapped[str] = mapped_column(Text)
    # Set for daily data so a date range can be read without parsing keys.
    calendar_date: Mapped[date | None] = mapped_column(Date)
    payload: Mapped[Any] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailySummary(Base):
    """One row per user and day, from the Garmin daily summary."""

    __tablename__ = "daily_summaries"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    calendar_date: Mapped[date] = mapped_column(Date, primary_key=True)
    steps: Mapped[int | None]
    step_goal: Mapped[int | None]
    distance_m: Mapped[int | None]
    floors_ascended: Mapped[float | None]
    floors_descended: Mapped[float | None]
    total_kcal: Mapped[float | None]
    active_kcal: Mapped[float | None]
    bmr_kcal: Mapped[float | None]
    highly_active_s: Mapped[int | None]
    active_s: Mapped[int | None]
    sedentary_s: Mapped[int | None]
    moderate_intensity_min: Mapped[int | None]
    vigorous_intensity_min: Mapped[int | None]
    resting_hr: Mapped[int | None]
    min_hr: Mapped[int | None]
    max_hr: Mapped[int | None]
    avg_stress: Mapped[int | None]
    max_stress: Mapped[int | None]
    body_battery_high: Mapped[int | None]
    body_battery_low: Mapped[int | None]
    body_battery_charged: Mapped[int | None]
    body_battery_drained: Mapped[int | None]
    avg_spo2: Mapped[float | None]
    lowest_spo2: Mapped[float | None]
    avg_waking_respiration: Mapped[float | None]


class SleepSession(Base):
    """The main sleep of the night that ends on calendar_date."""

    __tablename__ = "sleep_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    calendar_date: Mapped[date] = mapped_column(Date, primary_key=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sleep_s: Mapped[int | None]
    nap_s: Mapped[int | None]
    deep_s: Mapped[int | None]
    light_s: Mapped[int | None]
    rem_s: Mapped[int | None]
    awake_s: Mapped[int | None]
    awake_count: Mapped[int | None]
    score: Mapped[int | None]
    score_qualifier: Mapped[str | None] = mapped_column(Text)
    avg_respiration: Mapped[float | None]
    avg_stress: Mapped[float | None]
    avg_hrv: Mapped[float | None]
    hrv_status: Mapped[str | None] = mapped_column(Text)
    resting_hr: Mapped[int | None]
    body_battery_change: Mapped[int | None]


class HeartRateSample(Base):
    """Intraday heart rate, one row per measurement."""

    __tablename__ = "heart_rate_samples"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    bpm: Mapped[int] = mapped_column(SmallInteger)


class StressSample(Base):
    """Intraday stress level, 0 to 100."""

    __tablename__ = "stress_samples"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    level: Mapped[int] = mapped_column(SmallInteger)


class BodyBatterySample(Base):
    """Intraday body battery level, 0 to 100."""

    __tablename__ = "body_battery_samples"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    level: Mapped[int] = mapped_column(SmallInteger)


class RespirationSample(Base):
    """Intraday respiration rate."""

    __tablename__ = "respiration_samples"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    breaths_per_min: Mapped[float]


class HrvSummary(Base):
    """Heart rate variability for the night that ends on calendar_date."""

    __tablename__ = "hrv_summaries"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    calendar_date: Mapped[date] = mapped_column(Date, primary_key=True)
    weekly_avg: Mapped[int | None]
    last_night_avg: Mapped[int | None]
    last_night_5min_high: Mapped[int | None]
    baseline_low_upper: Mapped[int | None]
    baseline_balanced_low: Mapped[int | None]
    baseline_balanced_upper: Mapped[int | None]
    status: Mapped[str | None] = mapped_column(Text)


class HrvReading(Base):
    """Heart rate variability during sleep, one row per reading."""

    __tablename__ = "hrv_readings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    hrv_ms: Mapped[int] = mapped_column(SmallInteger)


class StepInterval(Base):
    """Steps per interval of the day, as Garmin buckets them."""

    __tablename__ = "step_intervals"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    steps: Mapped[int]


class TrainingReadiness(Base):
    """Training readiness. Garmin can report several per day, e.g. after a workout."""

    __tablename__ = "training_readiness"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    calendar_date: Mapped[date] = mapped_column(Date, index=True)
    score: Mapped[int | None]
    level: Mapped[str | None] = mapped_column(Text)
    feedback: Mapped[str | None] = mapped_column(Text)
    sleep_score: Mapped[int | None]
    recovery_time_min: Mapped[int | None]
    acute_load: Mapped[int | None]
    hrv_weekly_avg: Mapped[int | None]
    # How much each factor contributes to the score, 0 to 100.
    sleep_factor_pct: Mapped[int | None]
    recovery_time_factor_pct: Mapped[int | None]
    acwr_factor_pct: Mapped[int | None]
    stress_history_factor_pct: Mapped[int | None]
    hrv_factor_pct: Mapped[int | None]
    sleep_history_factor_pct: Mapped[int | None]


class TrainingStatus(Base):
    """Training status and load for a day, from the primary training device."""

    __tablename__ = "training_status"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    calendar_date: Mapped[date] = mapped_column(Date, primary_key=True)
    status_code: Mapped[int | None]
    status: Mapped[str | None] = mapped_column(Text)
    sport: Mapped[str | None] = mapped_column(Text)
    fitness_trend: Mapped[int | None]
    acute_load: Mapped[int | None]
    chronic_load: Mapped[int | None]
    # Acute to chronic workload ratio.
    acwr: Mapped[float | None]
    acwr_status: Mapped[str | None] = mapped_column(Text)
    # Four-week load per intensity, and how Garmin judges the mix.
    load_aerobic_low: Mapped[float | None]
    load_aerobic_high: Mapped[float | None]
    load_anaerobic: Mapped[float | None]
    load_balance: Mapped[str | None] = mapped_column(Text)


class Vo2Max(Base):
    """VO2 max estimates and acclimation on the day they were updated."""

    __tablename__ = "vo2max"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    calendar_date: Mapped[date] = mapped_column(Date, primary_key=True)
    running: Mapped[float | None]
    cycling: Mapped[float | None]
    heat_acclimation_pct: Mapped[int | None]
    altitude_acclimation: Mapped[int | None]


class RacePrediction(Base):
    """Predicted race times in seconds."""

    __tablename__ = "race_predictions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    calendar_date: Mapped[date] = mapped_column(Date, primary_key=True)
    time_5k_s: Mapped[int | None]
    time_10k_s: Mapped[int | None]
    time_half_marathon_s: Mapped[int | None]
    time_marathon_s: Mapped[int | None]


class FitnessAge(Base):
    __tablename__ = "fitness_ages"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    calendar_date: Mapped[date] = mapped_column(Date, primary_key=True)
    fitness_age: Mapped[float | None]
    chronological_age: Mapped[int | None]
    achievable_fitness_age: Mapped[float | None]


class PowerThreshold(Base):
    """Functional threshold power per sport, on the day it was set."""

    __tablename__ = "power_thresholds"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    sport: Mapped[str] = mapped_column(Text, primary_key=True)
    calendar_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ftp_watts: Mapped[int]
    power_to_weight: Mapped[float | None]


class RawFile(Base):
    """A file downloaded from Garmin, stored as received.

    kind "activity_original" is the archive holding the recording from the
    device, keyed by activity id. See ADR 12.
    """

    __tablename__ = "raw_files"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "kind", "resource_key", name="uq_raw_files_user_id_kind_resource_key"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    resource_key: Mapped[str] = mapped_column(Text)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Activity(Base):
    """One recorded activity with its summary figures."""

    __tablename__ = "activities"
    __table_args__ = (Index("ix_activities_user_id_start_at", "user_id", "start_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    activity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    type_key: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    is_parent: Mapped[bool] = mapped_column(default=False)
    duration_s: Mapped[float | None]
    moving_duration_s: Mapped[float | None]
    elapsed_duration_s: Mapped[float | None]
    distance_m: Mapped[float | None]
    elevation_gain_m: Mapped[float | None]
    elevation_loss_m: Mapped[float | None]
    avg_speed_mps: Mapped[float | None]
    max_speed_mps: Mapped[float | None]
    calories: Mapped[float | None]
    avg_hr: Mapped[float | None]
    max_hr: Mapped[float | None]
    avg_cadence: Mapped[float | None]
    avg_power: Mapped[float | None]
    max_power: Mapped[float | None]
    norm_power: Mapped[float | None]
    aerobic_training_effect: Mapped[float | None]
    anaerobic_training_effect: Mapped[float | None]
    training_effect_label: Mapped[str | None] = mapped_column(Text)
    training_load: Mapped[float | None]
    vo2max: Mapped[float | None]
    steps: Mapped[int | None]
    lap_count: Mapped[int | None]
    moderate_intensity_min: Mapped[int | None]
    vigorous_intensity_min: Mapped[int | None]
    location_name: Mapped[str | None] = mapped_column(Text)
    start_latitude: Mapped[float | None]
    start_longitude: Mapped[float | None]


class ActivityLap(Base):
    __tablename__ = "activity_laps"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    activity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lap_index: Mapped[int] = mapped_column(primary_key=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    intensity_type: Mapped[str | None] = mapped_column(Text)
    distance_m: Mapped[float | None]
    duration_s: Mapped[float | None]
    moving_duration_s: Mapped[float | None]
    elevation_gain_m: Mapped[float | None]
    elevation_loss_m: Mapped[float | None]
    avg_speed_mps: Mapped[float | None]
    max_speed_mps: Mapped[float | None]
    calories: Mapped[float | None]
    avg_hr: Mapped[float | None]
    max_hr: Mapped[float | None]
    avg_cadence: Mapped[float | None]
    avg_power: Mapped[float | None]
    max_power: Mapped[float | None]


class ActivityZone(Base):
    """Time spent in a heart rate or power zone during an activity."""

    __tablename__ = "activity_zones"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    activity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # "hr" or "power".
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    zone_number: Mapped[int] = mapped_column(primary_key=True)
    seconds: Mapped[float | None]
    low_boundary: Mapped[int | None]
