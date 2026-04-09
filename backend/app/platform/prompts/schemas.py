from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PromptCreate(BaseModel):
    conversation_id: str | None = None
    submitted_by: str | None = None
    content: str
    context: dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class PromptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str | None = None
    submitted_by: str | None = None
    content: str
    context_json: dict[str, Any]
    attachments_json: list[Any]
    status: str
    created_at: datetime
