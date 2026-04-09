from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventCreate(BaseModel):
    run_id: str | None = None
    run_step_id: str | None = None
    entity_type: str
    entity_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    actor_type: str | None = None
    actor_id: str | None = None
    trace_id: str | None = None


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str | None = None
    run_step_id: str | None = None
    entity_type: str
    entity_id: str
    event_type: str
    payload_json: dict[str, Any]
    actor_type: str | None = None
    actor_id: str | None = None
    trace_id: str | None = None
    created_at: datetime
