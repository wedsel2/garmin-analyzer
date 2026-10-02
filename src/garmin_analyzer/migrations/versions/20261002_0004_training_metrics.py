"""training metrics

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fitness_ages",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("fitness_age", sa.Double(), nullable=True),
        sa.Column("chronological_age", sa.Integer(), nullable=True),
        sa.Column("achievable_fitness_age", sa.Double(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_fitness_ages_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "calendar_date", name=op.f("pk_fitness_ages")),
    )
    op.create_table(
        "power_thresholds",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("sport", sa.Text(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("ftp_watts", sa.Integer(), nullable=False),
        sa.Column("power_to_weight", sa.Double(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_power_thresholds_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "sport", "calendar_date", name=op.f("pk_power_thresholds")
        ),
    )
    op.create_table(
        "race_predictions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("time_5k_s", sa.Integer(), nullable=True),
        sa.Column("time_10k_s", sa.Integer(), nullable=True),
        sa.Column("time_half_marathon_s", sa.Integer(), nullable=True),
        sa.Column("time_marathon_s", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_race_predictions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "calendar_date", name=op.f("pk_race_predictions")),
    )
    op.create_table(
        "training_readiness",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("level", sa.Text(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("sleep_score", sa.Integer(), nullable=True),
        sa.Column("recovery_time_min", sa.Integer(), nullable=True),
        sa.Column("acute_load", sa.Integer(), nullable=True),
        sa.Column("hrv_weekly_avg", sa.Integer(), nullable=True),
        sa.Column("sleep_factor_pct", sa.Integer(), nullable=True),
        sa.Column("recovery_time_factor_pct", sa.Integer(), nullable=True),
        sa.Column("acwr_factor_pct", sa.Integer(), nullable=True),
        sa.Column("stress_history_factor_pct", sa.Integer(), nullable=True),
        sa.Column("hrv_factor_pct", sa.Integer(), nullable=True),
        sa.Column("sleep_history_factor_pct", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_training_readiness_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "measured_at", name=op.f("pk_training_readiness")),
    )
    op.create_index(
        op.f("ix_training_readiness_calendar_date"),
        "training_readiness",
        ["calendar_date"],
        unique=False,
    )
    op.create_table(
        "training_status",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("sport", sa.Text(), nullable=True),
        sa.Column("fitness_trend", sa.Integer(), nullable=True),
        sa.Column("acute_load", sa.Integer(), nullable=True),
        sa.Column("chronic_load", sa.Integer(), nullable=True),
        sa.Column("acwr", sa.Double(), nullable=True),
        sa.Column("acwr_status", sa.Text(), nullable=True),
        sa.Column("load_aerobic_low", sa.Double(), nullable=True),
        sa.Column("load_aerobic_high", sa.Double(), nullable=True),
        sa.Column("load_anaerobic", sa.Double(), nullable=True),
        sa.Column("load_balance", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_training_status_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "calendar_date", name=op.f("pk_training_status")),
    )
    op.create_table(
        "vo2max",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("running", sa.Double(), nullable=True),
        sa.Column("cycling", sa.Double(), nullable=True),
        sa.Column("heat_acclimation_pct", sa.Integer(), nullable=True),
        sa.Column("altitude_acclimation", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_vo2max_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "calendar_date", name=op.f("pk_vo2max")),
    )


def downgrade() -> None:
    op.drop_table("vo2max")
    op.drop_table("training_status")
    op.drop_index(op.f("ix_training_readiness_calendar_date"), table_name="training_readiness")
    op.drop_table("training_readiness")
    op.drop_table("race_predictions")
    op.drop_table("power_thresholds")
    op.drop_table("fitness_ages")
