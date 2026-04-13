"""soft delete execution targets

Revision ID: 20260413_000005
Revises: 20260409_000004
Create Date: 2026-04-13 00:00:05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260413_000005"
down_revision: str | None = "20260409_000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "platform_execution_targets",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("platform_execution_targets", "archived_at")
