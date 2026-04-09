"""add platform primitives

Revision ID: 20260409_000003
Revises: 20260331_000002
Create Date: 2026-04-09 00:00:03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260409_000003"
down_revision: str | None = "20260331_000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_prompts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=255), nullable=True),
        sa.Column("submitted_by", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("attachments_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_prompts")),
    )
    op.create_table(
        "platform_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("prompt_id", sa.String(length=36), nullable=True),
        sa.Column("intent_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["platform_prompts.id"],
            name=op.f("fk_platform_runs_prompt_id_platform_prompts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_runs")),
    )
    op.create_index(
        op.f("ix_platform_runs_prompt_id"), "platform_runs", ["prompt_id"], unique=False
    )
    op.create_index(
        op.f("ix_platform_runs_intent_id"), "platform_runs", ["intent_id"], unique=False
    )
    op.create_table(
        "platform_run_steps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("step_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("approval_request_id", sa.String(length=36), nullable=True),
        sa.Column("tool_invocation_id", sa.String(length=36), nullable=True),
        sa.Column("artifact_id", sa.String(length=36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["platform_runs.id"],
            name=op.f("fk_platform_run_steps_run_id_platform_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_run_steps")),
    )
    op.create_index(
        op.f("ix_platform_run_steps_run_id"), "platform_run_steps", ["run_id"], unique=False
    )
    op.create_index(
        op.f("ix_platform_run_steps_approval_request_id"),
        "platform_run_steps",
        ["approval_request_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_platform_run_steps_tool_invocation_id"),
        "platform_run_steps",
        ["tool_invocation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_platform_run_steps_artifact_id"),
        "platform_run_steps",
        ["artifact_id"],
        unique=False,
    )
    op.create_table(
        "platform_tool_definitions",
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("namespace", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_schema_json", sa.JSON(), nullable=False),
        sa.Column("output_schema_json", sa.JSON(), nullable=False),
        sa.Column("side_effect_class", sa.String(length=32), nullable=False),
        sa.Column("destructive", sa.Boolean(), nullable=False),
        sa.Column("approval_mode", sa.String(length=32), nullable=False),
        sa.Column("approval_policy_key", sa.String(length=255), nullable=True),
        sa.Column("execution_mode", sa.String(length=32), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("tool_name", "version", name=op.f("pk_platform_tool_definitions")),
    )
    op.create_table(
        "platform_tool_invocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("run_step_id", sa.String(length=36), nullable=True),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("tool_version", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("normalized_input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("executor_name", sa.String(length=255), nullable=True),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["platform_runs.id"],
            name=op.f("fk_platform_tool_invocations_run_id_platform_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["run_step_id"],
            ["platform_run_steps.id"],
            name=op.f("fk_platform_tool_invocations_run_step_id_platform_run_steps"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_tool_invocations")),
    )
    op.create_index(
        op.f("ix_platform_tool_invocations_run_id"),
        "platform_tool_invocations",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_platform_tool_invocations_run_step_id"),
        "platform_tool_invocations",
        ["run_step_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_platform_tool_invocations_tool_name"),
        "platform_tool_invocations",
        ["tool_name"],
        unique=False,
    )
    op.create_table(
        "platform_approval_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("run_step_id", sa.String(length=36), nullable=True),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("decision_type", sa.String(length=64), nullable=False),
        sa.Column("policy_key", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_payload_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["platform_runs.id"],
            name=op.f("fk_platform_approval_requests_run_id_platform_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["run_step_id"],
            ["platform_run_steps.id"],
            name=op.f("fk_platform_approval_requests_run_step_id_platform_run_steps"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_approval_requests")),
    )
    op.create_index(
        op.f("ix_platform_approval_requests_run_id"),
        "platform_approval_requests",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_platform_approval_requests_run_step_id"),
        "platform_approval_requests",
        ["run_step_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_platform_approval_requests_target_id"),
        "platform_approval_requests",
        ["target_id"],
        unique=False,
    )
    op.create_table(
        "platform_approval_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("approval_request_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("decision_payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["approval_request_id"],
            ["platform_approval_requests.id"],
            name=op.f(
                "fk_platform_approval_decisions_approval_request_id_platform_approval_requests"
            ),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_approval_decisions")),
    )
    op.create_index(
        op.f("ix_platform_approval_decisions_approval_request_id"),
        "platform_approval_decisions",
        ["approval_request_id"],
        unique=False,
    )
    op.create_table(
        "platform_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("run_step_id", sa.String(length=36), nullable=True),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("uri", sa.Text(), nullable=True),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["platform_runs.id"],
            name=op.f("fk_platform_artifacts_run_id_platform_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["run_step_id"],
            ["platform_run_steps.id"],
            name=op.f("fk_platform_artifacts_run_step_id_platform_run_steps"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_artifacts")),
    )
    op.create_index(
        op.f("ix_platform_artifacts_run_id"), "platform_artifacts", ["run_id"], unique=False
    )
    op.create_index(
        op.f("ix_platform_artifacts_run_step_id"),
        "platform_artifacts",
        ["run_step_id"],
        unique=False,
    )
    op.create_table(
        "platform_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("run_step_id", sa.String(length=36), nullable=True),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("actor_type", sa.String(length=64), nullable=True),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("trace_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["platform_runs.id"], name=op.f("fk_platform_events_run_id_platform_runs")
        ),
        sa.ForeignKeyConstraint(
            ["run_step_id"],
            ["platform_run_steps.id"],
            name=op.f("fk_platform_events_run_step_id_platform_run_steps"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_events")),
    )
    op.create_index(op.f("ix_platform_events_run_id"), "platform_events", ["run_id"], unique=False)
    op.create_index(
        op.f("ix_platform_events_run_step_id"), "platform_events", ["run_step_id"], unique=False
    )
    op.create_index(
        op.f("ix_platform_events_entity_id"), "platform_events", ["entity_id"], unique=False
    )
    op.create_index(
        op.f("ix_platform_events_event_type"), "platform_events", ["event_type"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_platform_events_event_type"), table_name="platform_events")
    op.drop_index(op.f("ix_platform_events_entity_id"), table_name="platform_events")
    op.drop_index(op.f("ix_platform_events_run_step_id"), table_name="platform_events")
    op.drop_index(op.f("ix_platform_events_run_id"), table_name="platform_events")
    op.drop_table("platform_events")

    op.drop_index(op.f("ix_platform_artifacts_run_step_id"), table_name="platform_artifacts")
    op.drop_index(op.f("ix_platform_artifacts_run_id"), table_name="platform_artifacts")
    op.drop_table("platform_artifacts")

    op.drop_index(
        op.f("ix_platform_approval_decisions_approval_request_id"),
        table_name="platform_approval_decisions",
    )
    op.drop_table("platform_approval_decisions")

    op.drop_index(
        op.f("ix_platform_approval_requests_target_id"),
        table_name="platform_approval_requests",
    )
    op.drop_index(
        op.f("ix_platform_approval_requests_run_step_id"),
        table_name="platform_approval_requests",
    )
    op.drop_index(
        op.f("ix_platform_approval_requests_run_id"), table_name="platform_approval_requests"
    )
    op.drop_table("platform_approval_requests")

    op.drop_index(
        op.f("ix_platform_tool_invocations_tool_name"),
        table_name="platform_tool_invocations",
    )
    op.drop_index(
        op.f("ix_platform_tool_invocations_run_step_id"),
        table_name="platform_tool_invocations",
    )
    op.drop_index(
        op.f("ix_platform_tool_invocations_run_id"), table_name="platform_tool_invocations"
    )
    op.drop_table("platform_tool_invocations")

    op.drop_table("platform_tool_definitions")

    op.drop_index(op.f("ix_platform_run_steps_artifact_id"), table_name="platform_run_steps")
    op.drop_index(
        op.f("ix_platform_run_steps_tool_invocation_id"),
        table_name="platform_run_steps",
    )
    op.drop_index(
        op.f("ix_platform_run_steps_approval_request_id"),
        table_name="platform_run_steps",
    )
    op.drop_index(op.f("ix_platform_run_steps_run_id"), table_name="platform_run_steps")
    op.drop_table("platform_run_steps")

    op.drop_index(op.f("ix_platform_runs_intent_id"), table_name="platform_runs")
    op.drop_index(op.f("ix_platform_runs_prompt_id"), table_name="platform_runs")
    op.drop_table("platform_runs")

    op.drop_table("platform_prompts")
