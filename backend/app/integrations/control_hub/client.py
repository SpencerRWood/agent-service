from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.core.settings import settings


class ControlHubIntegrationError(RuntimeError):
    """Raised when Control Hub cannot process a request or returns invalid data."""


class ApprovalStatus(str):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ControlHubApprovalItemCreate(BaseModel):
    title: str
    description: str | None = None
    action_type: str
    payload_json: dict[str, Any] = Field(default_factory=dict)
    requested_by: str
    assigned_to: str | None = None


class ControlHubApprovalItemRead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    description: str | None = None
    action_type: str
    payload_json: dict[str, Any] = Field(default_factory=dict)
    status: str
    requested_by: str
    assigned_to: str | None = None
    created_at: str
    updated_at: str
    decided_at: str | None = None
    decided_by: str | None = None
    decision_reason: str | None = None


class ControlHubClient(Protocol):
    async def create_approval(
        self, item: ControlHubApprovalItemCreate
    ) -> ControlHubApprovalItemRead: ...

    async def get_approval(self, item_id: int) -> ControlHubApprovalItemRead: ...

    async def list_approvals(
        self,
        *,
        status: str | None = None,
        action_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[ControlHubApprovalItemRead]: ...


class HttpControlHubClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client

    @classmethod
    def from_settings(cls) -> HttpControlHubClient:
        return cls(
            base_url=settings.control_hub_base_url,
            timeout_seconds=settings.control_hub_timeout_seconds,
        )

    async def create_approval(
        self, item: ControlHubApprovalItemCreate
    ) -> ControlHubApprovalItemRead:
        return ControlHubApprovalItemRead.model_validate(
            await self._request("POST", "/approvals/", json=item.model_dump(mode="json"))
        )

    async def get_approval(self, item_id: int) -> ControlHubApprovalItemRead:
        return ControlHubApprovalItemRead.model_validate(
            await self._request("GET", f"/approvals/{item_id}")
        )

    async def list_approvals(
        self,
        *,
        status: str | None = None,
        action_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[ControlHubApprovalItemRead]:
        params = {
            "status": status,
            "action_type": action_type,
            "limit": limit,
            "offset": offset,
        }
        payload = await self._request("GET", "/approvals/", params=params)
        if not isinstance(payload, list):
            raise ControlHubIntegrationError("Control Hub approvals list response was not a list")

        return [ControlHubApprovalItemRead.model_validate(item) for item in payload]

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        if self._client is not None:
            response = await self._client.request(method, path, json=json, params=params)
        else:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.request(method, path, json=json, params=params)

        if response.status_code == 422:
            raise ControlHubIntegrationError(f"Control Hub validation error: {response.text}")

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ControlHubIntegrationError(
                f"Control Hub request failed with {exc.response.status_code}: {exc.response.text}"
            ) from exc

        return response.json()
