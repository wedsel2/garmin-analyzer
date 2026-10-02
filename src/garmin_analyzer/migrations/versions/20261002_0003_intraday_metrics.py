"""intraday metrics

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "body_battery_samples",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_body_battery_samples_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "measured_at", name=op.f("pk_body_battery_samples")),
    )
    op.create_table(
        "hrv_readings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hrv_ms", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_hrv_readings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "measured_at", name=op.f("pk_hrv_readings")),
    )
    op.create_table(
        "hrv_summaries",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("weekly_avg", sa.Integer(), nullable=True),
        sa.Column("last_night_avg", sa.Integer(), nullable=True),
        sa.Column("last_night_5min_high", sa.Integer(), nullable=True),
        sa.Column("baseline_low_upper", sa.Integer(), nullable=True),
        sa.Column("baseline_balanced_low", sa.Integer(), nullable=True),
        sa.Column("baseline_balanced_upper", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_hrv_summaries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "calendar_date", name=op.f("pk_hrv_summaries")),
    )
    op.create_table(
        "respiration_samples",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("breaths_per_min", sa.Double(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_respiration_samples_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "measured_at", name=op.f("pk_respiration_samples")),
    )
    op.create_table(
        "step_intervals",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("steps", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_step_intervals_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "start_at", name=op.f("pk_step_intervals")),
    )
    op.create_table(
        "stress_samples",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_stress_samples_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "measured_at", name=op.f("pk_stress_samples")),
    )


def downgrade() -> None:
    op.drop_table("stress_samples")
    op.drop_table("step_intervals")
    op.drop_table("respiration_samples")
    op.drop_table("hrv_summaries")
    op.drop_table("hrv_readings")
    op.drop_table("body_battery_samples")
