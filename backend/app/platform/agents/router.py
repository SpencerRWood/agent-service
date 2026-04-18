from __future__ import annotations

import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.session import get_db
from app.platform.agents.config_service import AgentCatalogConfigService
from app.platform.agents.repository import AgentCatalogConfigRepository
from app.platform.agents.schemas import (
    AgentCatalogConfigRead,
    AgentCatalogOverrideUpdate,
    AgentCatalogStructuredUpdate,
)

router = APIRouter(prefix="/platform/agents", tags=["platform-agents"])


def get_agent_catalog_config_service(
    db: AsyncSession = Depends(get_db),
) -> AgentCatalogConfigService:
    return AgentCatalogConfigService(AgentCatalogConfigRepository(db))


@router.get("/config", response_model=AgentCatalogConfigRead)
async def get_agent_catalog_config(
    service: AgentCatalogConfigService = Depends(get_agent_catalog_config_service),
) -> AgentCatalogConfigRead:
    return await service.get_config()


@router.put("/config/override", response_model=AgentCatalogConfigRead)
async def update_agent_catalog_override(
    request: AgentCatalogOverrideUpdate,
    service: AgentCatalogConfigService = Depends(get_agent_catalog_config_service),
) -> AgentCatalogConfigRead:
    try:
        return await service.update_override_yaml(request.yaml)
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid YAML: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.put("/config", response_model=AgentCatalogConfigRead)
async def replace_agent_catalog(
    request: AgentCatalogStructuredUpdate,
    service: AgentCatalogConfigService = Depends(get_agent_catalog_config_service),
) -> AgentCatalogConfigRead:
    try:
        return await service.replace_catalog(request.catalog)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.delete("/config/override", response_model=AgentCatalogConfigRead)
async def reset_agent_catalog_override(
    service: AgentCatalogConfigService = Depends(get_agent_catalog_config_service),
) -> AgentCatalogConfigRead:
    return await service.reset_override()
