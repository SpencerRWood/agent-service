from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.platform.artifacts.schemas import ArtifactRead
from app.platform.events.schemas import EventRead
from app.platform.execution_targets.schemas import ExecutionJobRead
from app.platform.runs.schemas import RunRead, RunStepRead


class TaskClass(StrEnum):
    CLASSIFY_ONLY = "classify_only"
    PLAN_ONLY = "plan_only"
    INSPECT_REPO = "inspect_repo"
    IMPLEMENT = "implement"
    DEBUG = "debug"
    REVIEW = "review"
    SUMMARIZE = "summarize"


class BackendName(StrEnum):
    LOCAL_LLM = "local_llm"
    CODEX = "codex"
    COPILOT_CLI = "copilot_cli"


class ExecutionPath(StrEnum):
    OPENCODE = "opencode"
    DIRECT = "direct"


class TaskArtifact(BaseModel):
    artifact_type: str
    title: str
    content: dict[str, Any] = Field(default_factory=dict)
    uri: str | None = None
    status: str = "created"
    provenance: dict[str, Any] = Field(default_factory=dict)


class AgentTaskRoutingDecision(BaseModel):
    execution_path: ExecutionPath
    selected_backend: BackendName
    fallback_backend: BackendName | None = None
    target_id: str | None = None
    route_profile: str | None = None
    reason: str
    debug: dict[str, Any] = Field(default_factory=dict)


class AgentTaskEnvelope(BaseModel):
    task_id: str
    run_id: str
    step_id: str
    trace_id: str
    task_class: TaskClass
    prompt: str
    repo: str | None = None
    project_path: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    routing: AgentTaskRoutingDecision
    source: dict[str, Any] = Field(default_factory=dict)
    approvals: dict[str, Any] = Field(default_factory=dict)
    branch_workflow: dict[str, Any] = Field(default_factory=dict)
    usage_limits: dict[str, Any] = Field(default_factory=dict)
    final_artifact_policy: dict[str, Any] = Field(default_factory=dict)


class AgentTaskCreateRequest(BaseModel):
    task_class: TaskClass
    prompt: str
    repo: str | None = None
    project_path: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    execution_path: ExecutionPath | None = None
    backend: BackendName | None = None
    fallback_backend: BackendName | None = None
    target_id: str | None = None
    route_profile: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)
    approvals: dict[str, Any] = Field(default_factory=dict)
    branch_workflow: dict[str, Any] = Field(default_factory=dict)
    usage_limits: dict[str, Any] = Field(default_factory=dict)
    final_artifact_policy: dict[str, Any] = Field(default_factory=dict)
    wait_for_completion: bool = False


class AgentTaskProgressCreate(BaseModel):
    run_id: str
    step_id: str
    trace_id: str | None = None
    event_type: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    actor_type: str = "worker"
    actor_id: str | None = None


class AgentTaskResult(BaseModel):
    status: str
    backend: BackendName
    execution_path: ExecutionPath
    summary: str
    raw_output: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[TaskArtifact] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    completed_at: datetime | None = None


class AgentTaskRead(BaseModel):
    task_id: str
    envelope: AgentTaskEnvelope
    run: RunRead
    step: RunStepRead
    job: ExecutionJobRead | None = None
    events: list[EventRead] = Field(default_factory=list)
    artifacts: list[ArtifactRead] = Field(default_factory=list)
    result: AgentTaskResult | None = None


class AgentTaskCreateResponse(BaseModel):
    task: AgentTaskRead
