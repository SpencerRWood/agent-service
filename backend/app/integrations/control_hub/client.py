from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import httpx

from app.core.logging import get_logger
from app.core.settings import settings
from app.integrations.control_hub.contract import (
    ApprovalStatus,
    ControlHubApprovalItemCreate,
    ControlHubApprovalItemRead,
    ControlHubContractError,
)

__all__ = [
    "ApprovalStatus",
    "ControlHubApprovalItemCreate",
    "ControlHubApprovalItemRead",
    "ControlHubClient",
    "ControlHubIntegrationError",
    "HttpControlHubClient",
]

logger = get_logger(__name__)


class ControlHubIntegrationError(RuntimeError):
    """Raised when Control Hub cannot process a request or returns invalid data."""


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
        try:
            return ControlHubApprovalItemRead.model_validate(
                await self._request("POST", "/approvals/", json=item.model_dump(mode="json"))
            )
        except ControlHubContractError as exc:
            raise ControlHubIntegrationError(
                f"Control Hub contract validation failed: {exc}"
            ) from exc

    async def get_approval(self, item_id: int) -> ControlHubApprovalItemRead:
        try:
            return ControlHubApprovalItemRead.model_validate(
                await self._request("GET", f"/approvals/{item_id}")
            )
        except ControlHubContractError as exc:
            raise ControlHubIntegrationError(
                f"Control Hub contract validation failed: {exc}"
            ) from exc

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

        try:
            return [ControlHubApprovalItemRead.model_validate(item) for item in payload]
        except ControlHubContractError as exc:
            raise ControlHubIntegrationError(
                f"Control Hub contract validation failed: {exc}"
            ) from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        logger.info(
            "Sending Control Hub request",
            extra={
                "event": "control_hub_request_started",
                "integration": "control_hub",
                "http": {"method": method, "path": path},
            },
        )
        if self._client is not None:
            response = await self._client.request(method, path, json=json, params=params)
        else:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.request(method, path, json=json, params=params)

        if response.status_code == 422:
            logger.warning(
                "Control Hub validation error",
                extra={
                    "event": "control_hub_validation_error",
                    "integration": "control_hub",
                    "http": {"method": method, "path": path, "status_code": response.status_code},
                },
            )
            raise ControlHubIntegrationError(f"Control Hub validation error: {response.text}")

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Control Hub request failed",
                extra={
                    "event": "control_hub_request_failed",
                    "integration": "control_hub",
                    "http": {
                        "method": method,
                        "path": path,
                        "status_code": exc.response.status_code,
                    },
                },
            )
            raise ControlHubIntegrationError(
                f"Control Hub request failed with {exc.response.status_code}: {exc.response.text}"
            ) from exc

        logger.info(
            "Control Hub request completed",
            extra={
                "event": "control_hub_request_completed",
                "integration": "control_hub",
                "http": {"method": method, "path": path, "status_code": response.status_code},
            },
        )
        return response.json()
