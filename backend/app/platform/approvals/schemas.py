from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApprovalRequestCreate(BaseModel):
    run_id: str | None = None
    run_step_id: str | None = None
    target_type: str
    target_id: str
    reason: str
    decision_type: str = "yes_no"
    policy_key: str | None = None
    requested_decision: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None


class ApprovalDecisionCreate(BaseModel):
    decision: str
    decided_by: str | None = None
    comment: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str | None = None
    run_step_id: str | None = None
    target_type: str
    target_id: str
    status: str
    decision_type: str
    policy_key: str | None = None
    reason: str
    request_payload_json: dict[str, Any]
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ApprovalDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    approval_request_id: str
    decision: str
    decided_by: str | None = None
    comment: str | None = None
    decision_payload_json: dict[str, Any]
    created_at: datetime
