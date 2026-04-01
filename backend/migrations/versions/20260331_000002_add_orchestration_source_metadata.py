"""add orchestration source metadata

Revision ID: 20260331_000002
Revises: 20260331_000001
Create Date: 2026-03-31 00:00:02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260331_000002"
down_revision: str | None = "20260331_000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orchestration_runs", sa.Column("source_metadata_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("orchestration_runs", "source_metadata_json")
