from fastapi import APIRouter, Depends

from app.platform.tools.schemas import ToolDefinition
from app.platform.tools.service import ToolRegistryService

router = APIRouter(prefix="/tools", tags=["platform-tools"])


def get_tool_registry_service() -> ToolRegistryService:
    return ToolRegistryService()


@router.get("/", response_model=list[ToolDefinition])
async def list_tools(
    service: ToolRegistryService = Depends(get_tool_registry_service),
) -> list[ToolDefinition]:
    return service.list_tools()


@router.get("/{tool_name:path}", response_model=ToolDefinition)
async def get_tool(
    tool_name: str,
    service: ToolRegistryService = Depends(get_tool_registry_service),
) -> ToolDefinition:
    return service.get_tool(tool_name)
