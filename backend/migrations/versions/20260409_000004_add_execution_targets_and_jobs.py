"""add execution targets and jobs

Revision ID: 20260409_000004
Revises: 20260409_000003
Create Date: 2026-04-09 00:00:04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260409_000004"
down_revision: str | None = "20260409_000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_execution_targets",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("executor_type", sa.String(length=64), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("user_name", sa.String(length=255), nullable=True),
        sa.Column("repo_root", sa.Text(), nullable=True),
        sa.Column("labels_json", sa.JSON(), nullable=False),
        sa.Column("supported_tools_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("secret_ref", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_execution_targets")),
    )
    op.create_table(
        "platform_execution_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("claimed_by", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["platform_execution_targets.id"],
            name=op.f("fk_platform_execution_jobs_target_id_platform_execution_targets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_execution_jobs")),
    )
    op.create_index(
        op.f("ix_platform_execution_jobs_target_id"),
        "platform_execution_jobs",
        ["target_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_platform_execution_jobs_tool_name"),
        "platform_execution_jobs",
        ["tool_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_platform_execution_jobs_tool_name"), table_name="platform_execution_jobs"
    )
    op.drop_index(
        op.f("ix_platform_execution_jobs_target_id"), table_name="platform_execution_jobs"
    )
    op.drop_table("platform_execution_jobs")
    op.drop_table("platform_execution_targets")
