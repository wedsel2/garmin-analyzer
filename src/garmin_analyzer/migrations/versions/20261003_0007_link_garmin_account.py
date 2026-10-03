"""link garmin account

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("garmin_links", sa.Column("garmin_account_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("garmin_links", "garmin_account_id")
