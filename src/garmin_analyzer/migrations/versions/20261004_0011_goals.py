"""goals

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goal_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("sport", sa.Text(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("target_time_s", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_goal_events_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goal_events")),
    )
    op.create_index(
        "ix_goal_events_user_id_event_date", "goal_events", ["user_id", "event_date"], unique=False
    )
    op.create_table(
        "weekly_goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "measure",
            sa.Enum("hours", "distance", "activities", name="goal_measure"),
            nullable=False,
        ),
        sa.Column("sport", sa.Text(), nullable=True),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_weekly_goals_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weekly_goals")),
    )
    op.create_index(op.f("ix_weekly_goals_user_id"), "weekly_goals", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_weekly_goals_user_id"), table_name="weekly_goals")
    op.drop_table("weekly_goals")
    op.drop_index("ix_goal_events_user_id_event_date", table_name="goal_events")
    op.drop_table("goal_events")
    sa.Enum(name="goal_measure").drop(op.get_bind())
