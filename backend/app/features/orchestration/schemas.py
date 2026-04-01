from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.features.orchestration.models import (
    ExecutionStatus,
    ProviderName,
    PullRequestStatus,
    RagStatus,
    WorkerType,
)


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionType(StrEnum):
    CODE_CHANGE = "code_change"


class WorkerTarget(StrEnum):
    AUTO = "auto"
    WORKER_B = "worker_b"
    AGENT_C = "agent_c"


class ProjectContext(BaseModel):
    project_id: str | None = None
    project_slug: str | None = None
    project_path: str | None = None


class ExecutionProposal(BaseModel):
    requested_change_summary: str
    repo: str
    project: ProjectContext | None = None
    worker_target: WorkerTarget = WorkerTarget.WORKER_B
    risk_level: RiskLevel
    risk_summary: str
    rollback_notes: list[str]
    acceptance_criteria: list[str]
    recommended_provider: ProviderName
    pr_success_conditions: list[str]
    constraints: list[str] = Field(default_factory=list)


class ApprovedWorkPackage(BaseModel):
    run_id: str
    approval_id: int
    provider: ProviderName
    repo: str
    project: ProjectContext | None = None
    worker_target: WorkerTarget = WorkerTarget.WORKER_B
    branch_strategy: str
    instructions: str
    constraints: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class WorkerExecutionResult(BaseModel):
    provider: str
    worker_target: WorkerTarget = WorkerTarget.WORKER_B
    branch_name: str
    commit_shas: list[str]
    pr_title: str
    pr_body: str
    pr_url: str
    pr_number: int
    execution_summary: str
    known_risks: list[str] = Field(default_factory=list)


class ArtifactStage(StrEnum):
    PROVISIONAL = "provisional"
    PROMOTED = "promoted"
    STALE = "stale"


class ArtifactFile(BaseModel):
    path: str
    media_type: str
    title: str
    content: str
    sha256: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_content(
        cls,
        *,
        path: str,
        media_type: str,
        title: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactFile:
        return cls(
            path=path,
            media_type=media_type,
            title=title,
            content=content,
            sha256=sha256(content.encode("utf-8")).hexdigest(),
            metadata=metadata or {},
        )


class ArtifactManifest(BaseModel):
    artifact_id: str
    repo: str
    project: ProjectContext | None = None
    provider: ProviderName
    worker_target: WorkerTarget
    stage: ArtifactStage
    generated_at: datetime
    source_run_id: str
    source_pr_url: str
    source_pr_number: int | None = None
    tags: list[str] = Field(default_factory=list)


class KnowledgeCaptureArtifact(BaseModel):
    manifest: ArtifactManifest
    implementation_summary: str
    operational_notes: list[str]
    decision_log: list[str]
    knowledge_chunks: list[str]
    documents: list[ArtifactFile] = Field(default_factory=list)
    promotion_history: list[dict[str, Any]] = Field(default_factory=list)
    source_pr_url: str
    provisional: bool = True


class PullRequestState(BaseModel):
    status: PullRequestStatus
    approved_by: list[str] = Field(default_factory=list)
    merged_at: datetime | None = None
    source: str = "event"


class RagPromotionState(BaseModel):
    status: RagStatus
    promoted_at: datetime | None = None
    reason: str | None = None


class CreateRunRequest(BaseModel):
    user_prompt: str
    repo: str | None = None
    project: ProjectContext | None = None
    worker_target: WorkerTarget | None = None
    requested_by: str | None = None
    assigned_to: str | None = None
    source_metadata: dict[str, Any] | None = None


class ChatToolContext(BaseModel):
    conversation_id: str | None = None
    message_id: str | None = None
    user_id: str | None = None
    username: str | None = None
    repo: str | None = None
    project: ProjectContext | None = None
    worker_target: WorkerTarget | None = None
    requested_by: str | None = None
    assigned_to: str | None = None
    labels: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class ChatToolCreateRunRequest(BaseModel):
    prompt: str
    context: ChatToolContext = Field(default_factory=ChatToolContext)


class ChatToolRunResponse(BaseModel):
    run_id: str
    approval_item_id: int | None = None
    execution_status: ExecutionStatus
    rag_status: RagStatus
    provider: ProviderName
    repo: str
    message: str
    next_action: str


class ChatToolStatusResponse(BaseModel):
    run_id: str
    approval_item_id: int | None = None
    execution_status: ExecutionStatus
    rag_status: RagStatus
    pr_status: PullRequestStatus
    pr_url: str | None = None
    repo: str
    summary: str


class PullRequestEventRequest(BaseModel):
    status: PullRequestStatus
    approved_by: list[str] = Field(default_factory=list)
    merged_at: datetime | None = None
    source: str = "webhook"


class RetryRunRequest(BaseModel):
    reason: str | None = None


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_prompt: str
    plan_summary: str
    risk_summary: str
    control_hub_approval_id: int | None = None
    action_type: str
    worker_type: WorkerType
    provider: ProviderName
    repo: str
    branch: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    pr_status: PullRequestStatus
    execution_status: ExecutionStatus
    rag_status: RagStatus
    failure_details: str | None = None
    source_metadata_json: dict[str, Any] | None = None
    proposal_json: dict[str, Any]
    work_package_json: dict[str, Any] | None = None
    execution_result_json: dict[str, Any] | None = None
    knowledge_artifact_json: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class RunListResponse(BaseModel):
    items: list[RunRead]


class ReconcileResponse(BaseModel):
    run: RunRead
    changed: bool
