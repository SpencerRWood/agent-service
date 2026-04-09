from __future__ import annotations

from fastapi import HTTPException

from app.platform.execution_targets.service import ExecutionTargetService


class RemoteExecutionDispatcher:
    def __init__(self, service: ExecutionTargetService) -> None:
        self._service = service

    async def dispatch(
        self,
        *,
        tool_name: str,
        payload: dict,
        explicit_target_id: str | None,
        routing_context: dict | None = None,
    ) -> dict | None:
        target = await self._service.choose_target(
            explicit_target_id=explicit_target_id,
            tool_name=tool_name,
            routing_context=routing_context,
        )
        if target is None or target.executor_type != "worker_agent":
            return None

        job = await self._service.create_job(
            target_id=target.id,
            tool_name=tool_name,
            payload=payload,
        )
        completed_job = await self._service.wait_for_job(job.id)
        if completed_job.status == "failed":
            detail = (completed_job.error_json or {}).get(
                "detail"
            ) or "Remote execution job failed."
            raise HTTPException(status_code=502, detail=str(detail))
        return completed_job.result_json


class NullRemoteExecutionDispatcher:
    async def dispatch(
        self,
        *,
        tool_name: str,
        payload: dict,
        explicit_target_id: str | None,
        routing_context: dict | None = None,
    ) -> dict | None:
        del tool_name, payload, explicit_target_id, routing_context
        return None
