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
    status: Mapped[LinkStatus] = mapped_column(
        Enum(LinkStatus, name="link_status", values_callable=lambda e: [m.value for m in e]),
        default=LinkStatus.ACTIVE,
    )
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
