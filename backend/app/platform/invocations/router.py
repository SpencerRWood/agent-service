from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.session import get_db
from app.platform.invocations.repository import ToolInvocationRepository
from app.platform.invocations.schemas import ToolInvocationRead, ToolInvocationRequest
from app.platform.invocations.service import ToolInvocationService
from app.platform.tools.service import ToolRegistryService

router = APIRouter(prefix="/tool-invocations", tags=["platform-tool-invocations"])


def get_tool_invocation_service(db: AsyncSession = Depends(get_db)) -> ToolInvocationService:
    return ToolInvocationService(
        repository=ToolInvocationRepository(db),
        tool_registry=ToolRegistryService(),
    )


@router.post("/", response_model=ToolInvocationRead, status_code=201)
async def create_tool_invocation(
    request: ToolInvocationRequest,
    service: ToolInvocationService = Depends(get_tool_invocation_service),
) -> ToolInvocationRead:
    return await service.create(request)


@router.get("/{invocation_id}", response_model=ToolInvocationRead)
async def get_tool_invocation(
    invocation_id: str,
    service: ToolInvocationService = Depends(get_tool_invocation_service),
) -> ToolInvocationRead:
    return await service.get(invocation_id)
