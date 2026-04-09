from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunCreate(BaseModel):
    prompt_id: str | None = None
    intent_id: str | None = None
    status: str = "created"


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    prompt_id: str | None = None
    intent_id: str | None = None
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RunStepCreate(BaseModel):
    step_type: str
    title: str
    status: str = "pending"
    sequence_index: int = 0
    input: dict[str, Any] = Field(default_factory=dict)


class RunStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    step_type: str
    title: str
    status: str
    sequence_index: int
    input_json: dict[str, Any] | None = None
    output_json: dict[str, Any] | None = None
    approval_request_id: str | None = None
    tool_invocation_id: str | None = None
    artifact_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
