from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.agents.models import AgentCatalogConfigRecord

DEFAULT_AGENT_CATALOG_CONFIG_KEY = "default"


class AgentCatalogConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_default(self) -> AgentCatalogConfigRecord | None:
        return await self._session.get(AgentCatalogConfigRecord, DEFAULT_AGENT_CATALOG_CONFIG_KEY)

    async def upsert_default(
        self,
        *,
        override_yaml: str,
        override_json: dict,
    ) -> AgentCatalogConfigRecord:
        record = await self.get_default()
        if record is None:
            record = AgentCatalogConfigRecord(
                config_key=DEFAULT_AGENT_CATALOG_CONFIG_KEY,
                override_yaml=override_yaml,
                override_json=override_json,
            )
            self._session.add(record)
        else:
            record.override_yaml = override_yaml
            record.override_json = override_json
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def update_backend_models(
        self,
        *,
        backend_models: dict[str, str] | None,
    ) -> AgentCatalogConfigRecord:
        record = await self.get_default()
        if record is None:
            record = AgentCatalogConfigRecord(
                config_key=DEFAULT_AGENT_CATALOG_CONFIG_KEY,
                backend_models_json=backend_models,
            )
            self._session.add(record)
        else:
            record.backend_models_json = backend_models
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def clear_default(self) -> None:
        record = await self.get_default()
        if record is None:
            return
        if record.backend_models_json is not None:
            record.override_yaml = None
            record.override_json = None
        else:
            await self._session.delete(record)
        await self._session.commit()
