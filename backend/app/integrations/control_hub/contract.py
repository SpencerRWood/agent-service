from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.core.settings import settings

REQUIRED_PATHS = {
    "/approvals/",
    "/approvals/{item_id}",
    "/approvals/{item_id}/approve",
    "/approvals/{item_id}/reject",
}
REQUIRED_SCHEMAS = {
    "ApprovalItemCreate",
    "ApprovalItemRead",
    "ApprovalItemApprove",
    "ApprovalItemReject",
    "ApprovalStatus",
}


class ControlHubContractError(RuntimeError):
    """Raised when the stored or remote Control Hub contract does not match expectations."""


def load_local_snapshot() -> dict[str, Any]:
    snapshot_path = Path(__file__).with_name("openapi_snapshot.json")
    return json.loads(snapshot_path.read_text())


def assert_snapshot_compatible(snapshot: dict[str, Any]) -> None:
    paths = snapshot.get("paths", {})
    schemas = snapshot.get("components", {}).get("schemas", {})

    missing_paths = sorted(REQUIRED_PATHS - set(paths))
    missing_schemas = sorted(REQUIRED_SCHEMAS - set(schemas))

    if missing_paths or missing_schemas:
        details: list[str] = []
        if missing_paths:
            details.append(f"missing paths: {', '.join(missing_paths)}")
        if missing_schemas:
            details.append(f"missing schemas: {', '.join(missing_schemas)}")
        raise ControlHubContractError(
            "Control Hub contract snapshot is incompatible: " + "; ".join(details)
        )


def assert_local_snapshot_compatible() -> None:
    assert_snapshot_compatible(load_local_snapshot())


async def validate_remote_openapi_if_enabled() -> None:
    if not settings.control_hub_enable_remote_schema_check:
        return

    async with httpx.AsyncClient(timeout=settings.control_hub_timeout_seconds) as client:
        response = await client.get(settings.control_hub_openapi_url)
        response.raise_for_status()
        assert_snapshot_compatible(response.json())
