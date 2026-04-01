from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class WorkerType(StrEnum):
    CODE = "code"


class ProviderName(StrEnum):
    CODEX = "codex"
    COPILOT_CLI = "copilot_cli"


class ExecutionStatus(StrEnum):
    PLANNED = "planned"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    PR_OPEN = "pr_open"
    PR_APPROVED = "pr_approved"
    DOCS_STAGED = "docs_staged"
    MERGED = "merged"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


class PullRequestStatus(StrEnum):
    NONE = "none"
    OPEN = "open"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    DISMISSED = "dismissed"
    MERGED = "merged"
    CLOSED = "closed"


class RagStatus(StrEnum):
    NOT_STARTED = "not_started"
    PROVISIONAL = "provisional"
    PROMOTED = "promoted"
    STALE = "stale"
    FAILED = "failed"


class OrchestrationRun(Base):
    __tablename__ = "orchestration_runs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    plan_summary: Mapped[str] = mapped_column(Text, nullable=False)
    risk_summary: Mapped[str] = mapped_column(Text, nullable=False)
    control_hub_approval_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    worker_type: Mapped[WorkerType] = mapped_column(
        SqlEnum(WorkerType, name="worker_type_enum"),
        default=WorkerType.CODE,
        nullable=False,
    )
    provider: Mapped[ProviderName] = mapped_column(
        SqlEnum(ProviderName, name="provider_name_enum"),
        nullable=False,
    )
    repo: Mapped[str] = mapped_column(String(255), nullable=False)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pr_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pr_status: Mapped[PullRequestStatus] = mapped_column(
        SqlEnum(PullRequestStatus, name="pull_request_status_enum"),
        default=PullRequestStatus.NONE,
        nullable=False,
    )
    execution_status: Mapped[ExecutionStatus] = mapped_column(
        SqlEnum(ExecutionStatus, name="execution_status_enum"),
        default=ExecutionStatus.PLANNED,
        nullable=False,
    )
    rag_status: Mapped[RagStatus] = mapped_column(
        SqlEnum(RagStatus, name="rag_status_enum"),
        default=RagStatus.NOT_STARTED,
        nullable=False,
    )
    failure_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    proposal_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    work_package_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    execution_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    knowledge_artifact_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
