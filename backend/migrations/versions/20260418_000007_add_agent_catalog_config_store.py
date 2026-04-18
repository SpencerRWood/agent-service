"""add agent catalog config store

Revision ID: 20260418_000007
Revises: 20260417_000006
Create Date: 2026-04-18 00:00:07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260418_000007"
down_revision: str | None = "20260417_000006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_agent_catalog_configs",
        sa.Column("config_key", sa.String(length=64), nullable=False),
        sa.Column("override_yaml", sa.Text(), nullable=True),
        sa.Column("override_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("config_key", name=op.f("pk_platform_agent_catalog_configs")),
    )


def downgrade() -> None:
    op.drop_table("platform_agent_catalog_configs")
