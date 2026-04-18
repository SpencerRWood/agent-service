from __future__ import annotations

from typing import Any

import yaml

from app.platform.agents.catalog import (
    OVERRIDE_CATALOG_PATH,
    delete_agent_catalog_override,
    load_agent_catalog_override_payload,
    load_default_catalog_payload,
    merge_catalog_payloads,
    render_catalog_yaml,
    save_agent_catalog_override_payload,
    validate_catalog_payload,
)
from app.platform.agents.repository import AgentCatalogConfigRepository
from app.platform.agents.schemas import AgentCatalogConfigRead


class AgentCatalogConfigService:
    def __init__(self, repository: AgentCatalogConfigRepository) -> None:
        self._repository = repository

    async def get_config(self) -> AgentCatalogConfigRead:
        default_payload = load_default_catalog_payload()
        override_payload = await self._load_override_payload()
        effective_payload = merge_catalog_payloads(default_payload, override_payload or {})
        if not isinstance(effective_payload, dict):
            raise ValueError("Effective agent catalog must be a mapping object.")
        validate_catalog_payload(effective_payload)
        return AgentCatalogConfigRead(
            default_path="backend/config/agents.yaml",
            override_path=str(OVERRIDE_CATALOG_PATH),
            has_override=override_payload is not None,
            default_yaml=render_catalog_yaml(default_payload),
            override_yaml=render_catalog_yaml(override_payload)
            if override_payload is not None
            else None,
            effective_yaml=render_catalog_yaml(effective_payload),
            default_catalog=default_payload,
            override_catalog=override_payload,
            effective_catalog=effective_payload,
        )

    async def update_override_yaml(self, yaml_text: str) -> AgentCatalogConfigRead:
        raw = yaml_text.strip()
        if not raw:
            await self.reset_override()
            return await self.get_config()

        payload = yaml.safe_load(raw)
        if payload is None:
            await self.reset_override()
            return await self.get_config()
        if not isinstance(payload, dict):
            raise ValueError("Override YAML must be a mapping object.")

        save_agent_catalog_override_payload(payload)
        await self._repository.upsert_default(
            override_yaml=render_catalog_yaml(payload),
            override_json=payload,
        )
        return await self.get_config()

    async def reset_override(self) -> AgentCatalogConfigRead:
        delete_agent_catalog_override()
        await self._repository.clear_default()
        return await self.get_config()

    async def _load_override_payload(self) -> dict[str, Any] | None:
        record = await self._repository.get_default()
        if record is not None and record.override_json is not None:
            payload = record.override_json
            if not isinstance(payload, dict):
                raise ValueError("Persisted agent catalog override must be a mapping object.")
            save_agent_catalog_override_payload(payload)
            return payload
        return load_agent_catalog_override_payload()
