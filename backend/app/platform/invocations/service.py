from fastapi import HTTPException, status

from app.platform.invocations.models import ToolInvocation
from app.platform.invocations.repository import ToolInvocationRepository
from app.platform.invocations.schemas import ToolInvocationRead, ToolInvocationRequest
from app.platform.tools.service import ToolRegistryService


class ToolInvocationService:
    def __init__(
        self,
        repository: ToolInvocationRepository,
        tool_registry: ToolRegistryService,
    ) -> None:
        self._repository = repository
        self._tool_registry = tool_registry

    async def create(self, request: ToolInvocationRequest) -> ToolInvocationRead:
        tool = self._tool_registry.get_tool(request.tool_name)
        status_value = (
            "pending_approval"
            if tool.approval_policy.get("mode") in {"required", "conditional"}
            and tool.side_effect.get("class") != "read"
            else "queued"
        )
        invocation = ToolInvocation(
            run_id=request.run_id,
            run_step_id=request.step_id,
            tool_name=tool.tool_name,
            tool_version=request.tool_version or tool.version,
            status=status_value,
            input_json=request.input,
            normalized_input_json=request.input,
            requested_by=request.requested_by,
        )
        created = await self._repository.create(invocation)
        return ToolInvocationRead.model_validate(created)

    async def get(self, invocation_id: str) -> ToolInvocationRead:
        invocation = await self._repository.get(invocation_id)
        if invocation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tool invocation not found",
            )
        return ToolInvocationRead.model_validate(invocation)
