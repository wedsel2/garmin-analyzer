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
