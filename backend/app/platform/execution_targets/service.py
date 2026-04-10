from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.core.settings import settings
from app.platform.execution_targets.health import target_is_online
from app.platform.execution_targets.models import ExecutionJob, ExecutionTarget
from app.platform.execution_targets.repository import ExecutionTargetRepository
from app.platform.execution_targets.routing import select_execution_target
from app.platform.execution_targets.schemas import (
    ExecutionJobListResponse,
    ExecutionJobRead,
    ExecutionTargetCreate,
    ExecutionTargetHealthRead,
    ExecutionTargetRead,
    ExecutionTargetUpdate,
    WorkerClaimRequest,
    WorkerHeartbeatRequest,
    WorkerJobCompleteRequest,
    WorkerJobFailRequest,
)


class ExecutionTargetService:
    def __init__(self, repository: ExecutionTargetRepository) -> None:
        self._repository = repository

    async def create_target(self, request: ExecutionTargetCreate) -> ExecutionTargetRead:
        target = ExecutionTarget(
            id=request.id,
            display_name=request.display_name,
            executor_type=request.executor_type,
            host=request.host,
            port=request.port,
            user_name=request.user_name,
            repo_root=request.repo_root,
            labels_json=request.labels,
            supported_tools_json=request.supported_tools,
            metadata_json=request.metadata,
            secret_ref=request.secret_ref,
            enabled=request.enabled,
            is_default=request.is_default,
        )
        created = await self._repository.create_target(target)
        return ExecutionTargetRead.model_validate(created)

    async def list_targets(self) -> list[ExecutionTargetRead]:
        return [
            ExecutionTargetRead.model_validate(target)
            for target in await self._repository.list_targets()
        ]

    async def update_target(
        self,
        target_id: str,
        request: ExecutionTargetUpdate,
    ) -> ExecutionTargetRead:
        target = await self._require_target(target_id)
        updates = request.model_dump(exclude_unset=True)
        if "labels" in updates:
            target.labels_json = updates.pop("labels")
        if "supported_tools" in updates:
            target.supported_tools_json = updates.pop("supported_tools")
        if "metadata" in updates:
            target.metadata_json = updates.pop("metadata")
        for field_name, field_value in updates.items():
            setattr(target, field_name, field_value)
        updated = await self._repository.update_target(target)
        return ExecutionTargetRead.model_validate(updated)

    async def get_target_health(self, target_id: str) -> ExecutionTargetHealthRead:
        target = await self._require_target(target_id)
        return ExecutionTargetHealthRead(
            target_id=target.id,
            display_name=target.display_name,
            enabled=target.enabled,
            online=target_is_online(target),
            executor_type=target.executor_type,
            last_seen_at=target.last_seen_at,
            labels=list(target.labels_json or []),
            supported_tools=list(target.supported_tools_json or []),
        )

    async def create_job(
        self,
        *,
        target_id: str,
        tool_name: str,
        payload: dict,
        job_id: str | None = None,
    ) -> ExecutionJobRead:
        await self._require_target(target_id)
        job = ExecutionJob(
            id=job_id or None,
            target_id=target_id,
            tool_name=tool_name,
            payload_json=payload,
        )
        created = await self._repository.create_job(job)
        return ExecutionJobRead.model_validate(created)

    async def list_jobs(
        self, *, target_id: str | None = None, limit: int = 50
    ) -> ExecutionJobListResponse:
        jobs = await self._repository.list_jobs(target_id=target_id, limit=limit)
        return ExecutionJobListResponse(
            items=[ExecutionJobRead.model_validate(job) for job in jobs]
        )

    async def get_job(self, job_id: str) -> ExecutionJobRead:
        job = await self._require_job(job_id)
        return ExecutionJobRead.model_validate(job)

    async def wait_for_job(
        self, job_id: str, *, timeout_seconds: float | None = None
    ) -> ExecutionJobRead:
        timeout_seconds = timeout_seconds or settings.remote_execution_wait_timeout_seconds
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            job = await self._repository.get_job(job_id)
            if job is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Execution job not found"
                )
            if job.status in {"completed", "failed"}:
                return ExecutionJobRead.model_validate(job)
            if asyncio.get_running_loop().time() >= deadline:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Timed out waiting for remote execution job completion.",
                )
            await asyncio.sleep(settings.remote_execution_poll_interval_seconds)

    async def choose_target(
        self,
        *,
        explicit_target_id: str | None,
        tool_name: str,
        routing_context: dict | None = None,
    ) -> ExecutionTargetRead | None:
        candidates = await self._repository.list_enabled_targets_for_tool(tool_name)
        target = select_execution_target(
            candidates=candidates,
            explicit_target_id=explicit_target_id,
            configured_default_target_id=settings.default_execution_target,
            routing_context=routing_context,
        )
        if explicit_target_id and target is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Target '{explicit_target_id}' is unavailable for tool '{tool_name}'.",
            )
        if target is None:
            return None
        return ExecutionTargetRead.model_validate(target)

    async def heartbeat(
        self,
        *,
        target_id: str,
        request: WorkerHeartbeatRequest,
    ) -> ExecutionTargetRead:
        target = await self._require_authorized_target(target_id)
        target.last_seen_at = datetime.now(UTC)
        target.metadata_json = {
            **(target.metadata_json or {}),
            "last_worker_id": request.worker_id,
            "last_heartbeat": request.metadata,
        }
        updated = await self._repository.update_target(target)
        return ExecutionTargetRead.model_validate(updated)

    async def claim_job(
        self,
        *,
        target_id: str,
        request: WorkerClaimRequest,
    ) -> ExecutionJobRead | None:
        await self._require_authorized_target(target_id)
        job = await self._repository.claim_next_job(
            target_id=target_id,
            worker_id=request.worker_id,
            supported_tools=request.supported_tools,
        )
        if job is None:
            return None
        return ExecutionJobRead.model_validate(job)

    async def complete_job(
        self,
        *,
        target_id: str,
        job_id: str,
        request: WorkerJobCompleteRequest,
    ) -> ExecutionJobRead:
        await self._require_authorized_target(target_id)
        job = await self._require_job(job_id)
        if job.target_id != target_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Job does not belong to target."
            )
        updated = await self._repository.complete_job(job, result_payload=request.result)
        return ExecutionJobRead.model_validate(updated)

    async def fail_job(
        self,
        *,
        target_id: str,
        job_id: str,
        request: WorkerJobFailRequest,
    ) -> ExecutionJobRead:
        await self._require_authorized_target(target_id)
        job = await self._require_job(job_id)
        if job.target_id != target_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Job does not belong to target."
            )
        updated = await self._repository.fail_job(job, error_payload=request.error)
        return ExecutionJobRead.model_validate(updated)

    async def _require_target(self, target_id: str) -> ExecutionTarget:
        target = await self._repository.get_target(target_id)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Execution target not found."
            )
        return target

    async def _require_authorized_target(self, target_id: str) -> ExecutionTarget:
        return await self._require_target(target_id)

    async def _require_job(self, job_id: str) -> ExecutionJob:
        job = await self._repository.get_job(job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Execution job not found."
            )
        return job


def validate_worker_secret(target: ExecutionTarget, provided_secret: str | None) -> None:
    expected = settings.worker_secret_refs.get(target.secret_ref or "")
    if target.secret_ref is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Execution target is not configured for worker authentication.",
        )
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Secret reference '{target.secret_ref}' is not configured on the server.",
        )
    if provided_secret != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid worker token."
        )
