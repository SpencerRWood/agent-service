"""add backend model config

Revision ID: 20260421_000008
Revises: 20260418_000007
Create Date: 2026-04-21 00:00:08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260421_000008"
down_revision: str | None = "20260418_000007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "platform_agent_catalog_configs",
        sa.Column("backend_models_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("platform_agent_catalog_configs", "backend_models_json")
