from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    tool_name: str
    display_name: str
    description: str
    version: str
    namespace: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    side_effect: dict[str, Any] = Field(default_factory=dict)
    approval_policy: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)
    observability: dict[str, Any] = Field(default_factory=dict)
    availability: dict[str, Any] = Field(default_factory=dict)


class ToolInvocationCreate(BaseModel):
    run_id: str | None = None
    step_id: str | None = None
    tool_name: str
    tool_version: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = None


ToolInvocationStatus = Literal[
    "draft",
    "pending_approval",
    "approved",
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "rejected",
    "expired",
]
