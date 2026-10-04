"""sync request

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "garmin_links",
        sa.Column("sync_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "garmin_links", sa.Column("sync_requested_days", sa.SmallInteger(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("garmin_links", "sync_requested_days")
    op.drop_column("garmin_links", "sync_requested_at")
