from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.features.orchestration.models import (
    ExecutionStatus,
    ProviderName,
    PullRequestStatus,
    RagStatus,
)
from app.features.orchestration.schemas import ProjectContext, WorkerTarget


class InteractionRequestCreate(BaseModel):
    prompt: str
    repo: str | None = None
    project: ProjectContext | None = None
    worker_target: WorkerTarget | None = None
    requested_by: str | None = None
    assigned_to: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    user_id: str | None = None
    username: str | None = None
    labels: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class InteractionApprovalDecisionRequest(BaseModel):
    decided_by: str
    decision_reason: str | None = None


class InteractionPullRequestEventRequest(BaseModel):
    status: PullRequestStatus
    approved_by: list[str] = Field(default_factory=list)
    merged_at: datetime | None = None
    source: str = "chat_client"


class InteractionRunResponse(BaseModel):
    run_id: str
    approval_item_id: int | None = None
    execution_status: ExecutionStatus
    rag_status: RagStatus
    pr_status: PullRequestStatus
    provider: ProviderName
    repo: str
    pr_url: str | None = None
    summary: str
    next_action: str
