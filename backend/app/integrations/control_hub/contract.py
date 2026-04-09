from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ControlHubContractError(RuntimeError):
    """Raised when Control Hub payloads do not match local Pydantic models."""


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ControlHubModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any):
        try:
            return super().model_validate(obj, *args, **kwargs)
        except ValidationError as exc:
            raise ControlHubContractError(str(exc)) from exc

    def model_copy(self, *, update: dict[str, Any] | None = None, deep: bool = False):
        try:
            data = self.model_dump()
            if update:
                data.update(update)
            return type(self).model_validate(data)
        except ControlHubContractError:
            raise
        except ValidationError as exc:
            raise ControlHubContractError(str(exc)) from exc

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class ControlHubApprovalItemCreate(ControlHubModel):
    title: str
    action_type: str
    requested_by: str
    description: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)
    assigned_to: str | None = None


class ControlHubApprovalItemRead(ControlHubModel):
    id: int
    title: str
    action_type: str
    payload_json: dict[str, Any]
    status: ApprovalStatus
    requested_by: str
    created_at: str
    updated_at: str
    description: str | None = None
    assigned_to: str | None = None
    decided_at: str | None = None
    decided_by: str | None = None
    decision_reason: str | None = None


class ControlHubApprovalItemApprove(ControlHubModel):
    decided_by: str
    decision_reason: str | None = None


class ControlHubApprovalItemReject(ControlHubModel):
    decided_by: str
    decision_reason: str
