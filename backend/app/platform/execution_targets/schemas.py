from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExecutionTargetCreate(BaseModel):
    id: str
    display_name: str
    executor_type: str = "worker_agent"
    host: str | None = None
    port: int | None = None
    user_name: str | None = None
    repo_root: str | None = None
    labels: list[str] = Field(default_factory=list)
    supported_tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    secret_ref: str | None = None
    enabled: bool = True
    is_default: bool = False


class ExecutionTargetUpdate(BaseModel):
    display_name: str | None = None
    host: str | None = None
    port: int | None = None
    user_name: str | None = None
    repo_root: str | None = None
    labels: list[str] | None = None
    supported_tools: list[str] | None = None
    metadata: dict[str, Any] | None = None
    secret_ref: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None


class ExecutionTargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    executor_type: str
    host: str | None = None
    port: int | None = None
    user_name: str | None = None
    repo_root: str | None = None
    labels_json: list[str]
    supported_tools_json: list[str]
    metadata_json: dict[str, Any]
    secret_ref: str | None = None
    enabled: bool
    is_default: bool
    last_seen_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ExecutionTargetHealthRead(BaseModel):
    target_id: str
    display_name: str
    enabled: bool
    online: bool
    executor_type: str
    last_seen_at: datetime | None = None
    labels: list[str] = Field(default_factory=list)
    supported_tools: list[str] = Field(default_factory=list)


class ExecutionJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    target_id: str
    tool_name: str
    status: str
    payload_json: dict[str, Any]
    result_json: dict[str, Any] | None = None
    error_json: dict[str, Any] | None = None
    claimed_by: str | None = None
    created_at: datetime
    claimed_at: datetime | None = None
    completed_at: datetime | None = None


class ExecutionJobListResponse(BaseModel):
    items: list[ExecutionJobRead]


class WorkerHeartbeatRequest(BaseModel):
    worker_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkerClaimRequest(BaseModel):
    worker_id: str
    supported_tools: list[str] = Field(default_factory=list)


class WorkerJobClaimResponse(BaseModel):
    job: ExecutionJobRead | None = None


class WorkerJobCompleteRequest(BaseModel):
    worker_id: str
    result: dict[str, Any]


class WorkerJobFailRequest(BaseModel):
    worker_id: str
    error: dict[str, Any]
