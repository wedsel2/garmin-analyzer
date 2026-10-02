"""daily summaries, sleep sessions, heart rate samples

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_summaries",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("steps", sa.Integer(), nullable=True),
        sa.Column("step_goal", sa.Integer(), nullable=True),
        sa.Column("distance_m", sa.Integer(), nullable=True),
        sa.Column("floors_ascended", sa.Double(), nullable=True),
        sa.Column("floors_descended", sa.Double(), nullable=True),
        sa.Column("total_kcal", sa.Double(), nullable=True),
        sa.Column("active_kcal", sa.Double(), nullable=True),
        sa.Column("bmr_kcal", sa.Double(), nullable=True),
        sa.Column("highly_active_s", sa.Integer(), nullable=True),
        sa.Column("active_s", sa.Integer(), nullable=True),
        sa.Column("sedentary_s", sa.Integer(), nullable=True),
        sa.Column("moderate_intensity_min", sa.Integer(), nullable=True),
        sa.Column("vigorous_intensity_min", sa.Integer(), nullable=True),
        sa.Column("resting_hr", sa.Integer(), nullable=True),
        sa.Column("min_hr", sa.Integer(), nullable=True),
        sa.Column("max_hr", sa.Integer(), nullable=True),
        sa.Column("avg_stress", sa.Integer(), nullable=True),
        sa.Column("max_stress", sa.Integer(), nullable=True),
        sa.Column("body_battery_high", sa.Integer(), nullable=True),
        sa.Column("body_battery_low", sa.Integer(), nullable=True),
        sa.Column("body_battery_charged", sa.Integer(), nullable=True),
        sa.Column("body_battery_drained", sa.Integer(), nullable=True),
        sa.Column("avg_spo2", sa.Double(), nullable=True),
        sa.Column("lowest_spo2", sa.Double(), nullable=True),
        sa.Column("avg_waking_respiration", sa.Double(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_daily_summaries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "calendar_date", name=op.f("pk_daily_summaries")),
    )
    op.create_table(
        "heart_rate_samples",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bpm", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_heart_rate_samples_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "measured_at", name=op.f("pk_heart_rate_samples")),
    )
    op.create_table(
        "sleep_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sleep_s", sa.Integer(), nullable=True),
        sa.Column("nap_s", sa.Integer(), nullable=True),
        sa.Column("deep_s", sa.Integer(), nullable=True),
        sa.Column("light_s", sa.Integer(), nullable=True),
        sa.Column("rem_s", sa.Integer(), nullable=True),
        sa.Column("awake_s", sa.Integer(), nullable=True),
        sa.Column("awake_count", sa.Integer(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("score_qualifier", sa.Text(), nullable=True),
        sa.Column("avg_respiration", sa.Double(), nullable=True),
        sa.Column("avg_stress", sa.Double(), nullable=True),
        sa.Column("avg_hrv", sa.Double(), nullable=True),
        sa.Column("hrv_status", sa.Text(), nullable=True),
        sa.Column("resting_hr", sa.Integer(), nullable=True),
        sa.Column("body_battery_change", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_sleep_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "calendar_date", name=op.f("pk_sleep_sessions")),
    )


def downgrade() -> None:
    op.drop_table("sleep_sessions")
    op.drop_table("heart_rate_samples")
    op.drop_table("daily_summaries")
