from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.platform.tools.schemas import ToolInvocationCreate


class ToolInvocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str | None = None
    run_step_id: str | None = None
    tool_name: str
    tool_version: str | None = None
    status: str
    input_json: dict[str, Any]
    normalized_input_json: dict[str, Any] | None = None
    output_json: dict[str, Any] | None = None
    error_json: dict[str, Any] | None = None
    executor_name: str | None = None
    requested_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class ToolInvocationRequest(ToolInvocationCreate):
    pass
