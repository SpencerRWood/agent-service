"""add run idempotency key

Revision ID: 20260417_000006
Revises: 20260413_000005
Create Date: 2026-04-17 00:00:06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260417_000006"
down_revision: str | None = "20260413_000005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "platform_runs",
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_platform_runs_idempotency_key"),
        "platform_runs",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_platform_runs_idempotency_key"), table_name="platform_runs")
    op.drop_column("platform_runs", "idempotency_key")
