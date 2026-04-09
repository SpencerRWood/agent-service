from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ArtifactCreate(BaseModel):
    run_id: str | None = None
    run_step_id: str | None = None
    artifact_type: str
    title: str
    content: dict[str, Any] = Field(default_factory=dict)
    uri: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    status: str = "created"


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str | None = None
    run_step_id: str | None = None
    artifact_type: str
    title: str
    content_json: dict[str, Any]
    uri: str | None = None
    provenance_json: dict[str, Any]
    status: str
    created_at: datetime
