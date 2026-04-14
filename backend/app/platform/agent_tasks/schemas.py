from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.platform.approvals.schemas import ApprovalDecisionRead, ApprovalRequestRead
from app.platform.artifacts.schemas import ArtifactRead
from app.platform.events.schemas import EventRead
from app.platform.execution_targets.schemas import ExecutionJobRead
from app.platform.runs.schemas import RunRead, RunStepRead


class TaskClass(StrEnum):
    CLASSIFY_ONLY = "classify_only"
    ANSWER_QUESTION = "answer_question"
    SUMMARIZE = "summarize"
    PLAN_ONLY = "plan_only"
    INSPECT_REPO = "inspect_repo"
    ANALYZE = "analyze"
    IMPLEMENT = "implement"
    REFACTOR = "refactor"
    DEBUG = "debug"
    REVIEW = "review"
    TEST = "test"
    DOCUMENT = "document"


class BackendName(StrEnum):
    LOCAL_LLM = "local_llm"
    CODEX = "codex"
    COPILOT_CLI = "copilot_cli"


class ExecutionMode(StrEnum):
    OPENCODE = "opencode"


class TaskState(StrEnum):
    QUEUED = "queued"
    PREFLIGHT_CHECK = "preflight_check"
    READY_TO_RUN = "ready_to_run"
    RUNNING = "running"
    RATE_LIMITED = "rate_limited"
    DEFERRED_UNTIL_RESET = "deferred_until_reset"
    REROUTED = "rerouted"
    COMPLETED = "completed"
    FAILED = "failed"


class ReasonCode(StrEnum):
    TASK_CLASS_MATCH = "task_class_match"
    CODEX_AVAILABLE = "codex_available"
    CODEX_RATE_LIMITED = "codex_rate_limited"
    COPILOT_AVAILABLE = "copilot_available"
    LOCAL_LLM_SUFFICIENT = "local_llm_sufficient"
    REPO_CONTEXT_REQUIRED = "repo_context_required"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    RUNTIME_RATE_LIMITED = "runtime_rate_limited"


class TaskArtifact(BaseModel):
    artifact_type: str
    title: str
    content: dict[str, Any] = Field(default_factory=dict)
    uri: str | None = None
    status: str = "created"
    provenance: dict[str, Any] = Field(default_factory=dict)


class WorkerDispatchDecision(BaseModel):
    target_id: str | None = None
    route_profile: str | None = None
    reason: str
    debug: dict[str, Any] = Field(default_factory=dict)


class AgentTaskEnvelope(BaseModel):
    task_id: str
    run_id: str
    step_id: str
    correlation_id: str
    user_prompt: str
    normalized_goal: str
    task_class: TaskClass
    target_repo: str | None = None
    target_branch: str | None = None
    execution_mode: ExecutionMode = ExecutionMode.OPENCODE
    allowed_backends: list[BackendName] = Field(default_factory=list)
    preferred_backend: BackendName | None = None
    approval_policy: dict[str, Any] = Field(default_factory=dict)
    timeout_policy: dict[str, Any] = Field(default_factory=dict)
    return_artifacts: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    dispatch: WorkerDispatchDecision


class AgentTaskCreateRequest(BaseModel):
    task_class: TaskClass | None = None
    prompt: str
    repo: str | None = None
    target_branch: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    execution_mode: ExecutionMode = ExecutionMode.OPENCODE
    allowed_backends: list[BackendName] = Field(default_factory=list)
    backend: BackendName | None = None
    fallback_backend: BackendName | None = None
    target_id: str | None = None
    route_profile: str | None = None
    approval_policy: dict[str, Any] = Field(default_factory=dict)
    timeout_policy: dict[str, Any] = Field(default_factory=dict)
    return_artifacts: list[str] = Field(default_factory=lambda: ["summary"])
    metadata: dict[str, Any] = Field(default_factory=dict)
    wait_for_completion: bool = False


class AgentTaskProgressCreate(BaseModel):
    run_id: str
    step_id: str
    correlation_id: str | None = None
    state: TaskState | None = None
    event_type: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    actor_type: str = "worker"
    actor_id: str | None = None


class AgentTaskResult(BaseModel):
    state: TaskState
    backend: BackendName | None = None
    execution_mode: ExecutionMode
    summary: str
    reason_code: str | None = None
    retry_after: datetime | None = None
    raw_output: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[TaskArtifact] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    completed_at: datetime | None = None


class AgentTaskRead(BaseModel):
    task_id: str
    state: TaskState
    envelope: AgentTaskEnvelope
    run: RunRead
    step: RunStepRead
    job: ExecutionJobRead | None = None
    events: list[EventRead] = Field(default_factory=list)
    approvals: list[ApprovalRequestRead] = Field(default_factory=list)
    approval_decisions: list[ApprovalDecisionRead] = Field(default_factory=list)
    artifacts: list[ArtifactRead] = Field(default_factory=list)
    result: AgentTaskResult | None = None


class AgentTaskCreateResponse(BaseModel):
    task: AgentTaskRead
