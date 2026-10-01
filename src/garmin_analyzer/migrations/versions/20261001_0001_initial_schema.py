"""initial schema

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "garmin_links",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_tokens", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.Enum("active", "needs_relink", name="link_status"), nullable=False),
        sa.Column(
            "linked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_garmin_links_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_garmin_links")),
    )
    op.create_table(
        "raw_payloads",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("resource_key", sa.Text(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_raw_payloads_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_payloads")),
        sa.UniqueConstraint(
            "user_id",
            "endpoint",
            "resource_key",
            name="uq_raw_payloads_user_id_endpoint_resource_key",
        ),
    )
    op.create_index(
        "ix_raw_payloads_user_id_endpoint_calendar_date",
        "raw_payloads",
        ["user_id", "endpoint", "calendar_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_raw_payloads_user_id_endpoint_calendar_date", table_name="raw_payloads")
    op.drop_table("raw_payloads")
    op.drop_table("garmin_links")
    op.drop_table("users")
    sa.Enum(name="link_status").drop(op.get_bind())
