"""activities and raw files

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activities",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type_key", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("is_parent", sa.Boolean(), nullable=False),
        sa.Column("duration_s", sa.Double(), nullable=True),
        sa.Column("moving_duration_s", sa.Double(), nullable=True),
        sa.Column("elapsed_duration_s", sa.Double(), nullable=True),
        sa.Column("distance_m", sa.Double(), nullable=True),
        sa.Column("elevation_gain_m", sa.Double(), nullable=True),
        sa.Column("elevation_loss_m", sa.Double(), nullable=True),
        sa.Column("avg_speed_mps", sa.Double(), nullable=True),
        sa.Column("max_speed_mps", sa.Double(), nullable=True),
        sa.Column("calories", sa.Double(), nullable=True),
        sa.Column("avg_hr", sa.Double(), nullable=True),
        sa.Column("max_hr", sa.Double(), nullable=True),
        sa.Column("avg_cadence", sa.Double(), nullable=True),
        sa.Column("avg_power", sa.Double(), nullable=True),
        sa.Column("max_power", sa.Double(), nullable=True),
        sa.Column("norm_power", sa.Double(), nullable=True),
        sa.Column("aerobic_training_effect", sa.Double(), nullable=True),
        sa.Column("anaerobic_training_effect", sa.Double(), nullable=True),
        sa.Column("training_effect_label", sa.Text(), nullable=True),
        sa.Column("training_load", sa.Double(), nullable=True),
        sa.Column("vo2max", sa.Double(), nullable=True),
        sa.Column("steps", sa.Integer(), nullable=True),
        sa.Column("lap_count", sa.Integer(), nullable=True),
        sa.Column("moderate_intensity_min", sa.Integer(), nullable=True),
        sa.Column("vigorous_intensity_min", sa.Integer(), nullable=True),
        sa.Column("location_name", sa.Text(), nullable=True),
        sa.Column("start_latitude", sa.Double(), nullable=True),
        sa.Column("start_longitude", sa.Double(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_activities_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "activity_id", name=op.f("pk_activities")),
    )
    op.create_index(
        "ix_activities_user_id_start_at", "activities", ["user_id", "start_at"], unique=False
    )
    op.create_table(
        "activity_laps",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("lap_index", sa.Integer(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("intensity_type", sa.Text(), nullable=True),
        sa.Column("distance_m", sa.Double(), nullable=True),
        sa.Column("duration_s", sa.Double(), nullable=True),
        sa.Column("moving_duration_s", sa.Double(), nullable=True),
        sa.Column("elevation_gain_m", sa.Double(), nullable=True),
        sa.Column("elevation_loss_m", sa.Double(), nullable=True),
        sa.Column("avg_speed_mps", sa.Double(), nullable=True),
        sa.Column("max_speed_mps", sa.Double(), nullable=True),
        sa.Column("calories", sa.Double(), nullable=True),
        sa.Column("avg_hr", sa.Double(), nullable=True),
        sa.Column("max_hr", sa.Double(), nullable=True),
        sa.Column("avg_cadence", sa.Double(), nullable=True),
        sa.Column("avg_power", sa.Double(), nullable=True),
        sa.Column("max_power", sa.Double(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_activity_laps_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "activity_id", "lap_index", name=op.f("pk_activity_laps")
        ),
    )
    op.create_table(
        "activity_zones",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("zone_number", sa.Integer(), nullable=False),
        sa.Column("seconds", sa.Double(), nullable=True),
        sa.Column("low_boundary", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_activity_zones_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "activity_id", "kind", "zone_number", name=op.f("pk_activity_zones")
        ),
    )
    op.create_table(
        "raw_files",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("resource_key", sa.Text(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_raw_files_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_files")),
        sa.UniqueConstraint(
            "user_id", "kind", "resource_key", name="uq_raw_files_user_id_kind_resource_key"
        ),
    )


def downgrade() -> None:
    op.drop_table("raw_files")
    op.drop_table("activity_zones")
    op.drop_table("activity_laps")
    op.drop_index("ix_activities_user_id_start_at", table_name="activities")
    op.drop_table("activities")
