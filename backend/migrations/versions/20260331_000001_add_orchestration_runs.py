"""add orchestration runs

Revision ID: 20260331_000001
Revises:
Create Date: 2026-03-31 00:00:01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260331_000001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


worker_type_enum = sa.Enum("code", name="worker_type_enum")
provider_name_enum = sa.Enum("codex", "copilot_cli", name="provider_name_enum")
pull_request_status_enum = sa.Enum(
    "none",
    "open",
    "approved",
    "changes_requested",
    "dismissed",
    "merged",
    "closed",
    name="pull_request_status_enum",
)
execution_status_enum = sa.Enum(
    "planned",
    "awaiting_approval",
    "approved",
    "executing",
    "pr_open",
    "pr_approved",
    "docs_staged",
    "merged",
    "completed",
    "rejected",
    "failed",
    name="execution_status_enum",
)
rag_status_enum = sa.Enum(
    "not_started",
    "provisional",
    "promoted",
    "stale",
    "failed",
    name="rag_status_enum",
)


def upgrade() -> None:
    bind = op.get_bind()
    worker_type_enum.create(bind, checkfirst=True)
    provider_name_enum.create(bind, checkfirst=True)
    pull_request_status_enum.create(bind, checkfirst=True)
    execution_status_enum.create(bind, checkfirst=True)
    rag_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "orchestration_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("plan_summary", sa.Text(), nullable=False),
        sa.Column("risk_summary", sa.Text(), nullable=False),
        sa.Column("control_hub_approval_id", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("worker_type", worker_type_enum, nullable=False),
        sa.Column("provider", provider_name_enum, nullable=False),
        sa.Column("repo", sa.String(length=255), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("pr_url", sa.Text(), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("pr_status", pull_request_status_enum, nullable=False),
        sa.Column("execution_status", execution_status_enum, nullable=False),
        sa.Column("rag_status", rag_status_enum, nullable=False),
        sa.Column("failure_details", sa.Text(), nullable=True),
        sa.Column("proposal_json", sa.JSON(), nullable=False),
        sa.Column("work_package_json", sa.JSON(), nullable=True),
        sa.Column("execution_result_json", sa.JSON(), nullable=True),
        sa.Column("knowledge_artifact_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orchestration_runs")),
    )


def downgrade() -> None:
    op.drop_table("orchestration_runs")

    bind = op.get_bind()
    rag_status_enum.drop(bind, checkfirst=True)
    execution_status_enum.drop(bind, checkfirst=True)
    pull_request_status_enum.drop(bind, checkfirst=True)
    provider_name_enum.drop(bind, checkfirst=True)
    worker_type_enum.drop(bind, checkfirst=True)
