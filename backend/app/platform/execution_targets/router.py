from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.session import get_db
from app.platform.execution_targets.repository import ExecutionTargetRepository
from app.platform.execution_targets.schemas import (
    ExecutionJobListResponse,
    ExecutionJobRead,
    ExecutionTargetCreate,
    ExecutionTargetHealthRead,
    ExecutionTargetRead,
    ExecutionTargetUpdate,
    WorkerClaimRequest,
    WorkerHeartbeatRequest,
    WorkerJobClaimResponse,
    WorkerJobCompleteRequest,
    WorkerJobFailRequest,
    WorkerJobRequeueRequest,
)
from app.platform.execution_targets.service import ExecutionTargetService, validate_worker_secret

router = APIRouter(prefix="/admin/execution-targets", tags=["platform-execution-targets"])
worker_router = APIRouter(prefix="/worker/execution-targets", tags=["platform-worker-targets"])
job_router = APIRouter(prefix="/admin/execution-jobs", tags=["platform-execution-jobs"])


def get_execution_target_service(db: AsyncSession = Depends(get_db)) -> ExecutionTargetService:
    return ExecutionTargetService(ExecutionTargetRepository(db))


@router.post("/", response_model=ExecutionTargetRead, status_code=201)
async def create_execution_target(
    request: ExecutionTargetCreate,
    service: ExecutionTargetService = Depends(get_execution_target_service),
) -> ExecutionTargetRead:
    return await service.create_target(request)


@router.get("/", response_model=list[ExecutionTargetRead])
async def list_execution_targets(
    service: ExecutionTargetService = Depends(get_execution_target_service),
) -> list[ExecutionTargetRead]:
    return await service.list_targets()


@router.patch("/{target_id}", response_model=ExecutionTargetRead)
async def update_execution_target(
    target_id: str,
    request: ExecutionTargetUpdate,
    service: ExecutionTargetService = Depends(get_execution_target_service),
) -> ExecutionTargetRead:
    return await service.update_target(target_id, request)


@router.delete("/{target_id}", status_code=204)
async def delete_execution_target(
    target_id: str,
    service: ExecutionTargetService = Depends(get_execution_target_service),
) -> Response:
    await service.delete_target(target_id)
    return Response(status_code=204)


@router.get("/{target_id}/health", response_model=ExecutionTargetHealthRead)
async def get_execution_target_health(
    target_id: str,
    service: ExecutionTargetService = Depends(get_execution_target_service),
) -> ExecutionTargetHealthRead:
    return await service.get_target_health(target_id)


@job_router.get("/", response_model=ExecutionJobListResponse)
async def list_execution_jobs(
    target_id: str | None = None,
    limit: int = 50,
    service: ExecutionTargetService = Depends(get_execution_target_service),
) -> ExecutionJobListResponse:
    return await service.list_jobs(target_id=target_id, limit=limit)


@job_router.get("/{job_id}", response_model=ExecutionJobRead)
async def get_execution_job(
    job_id: str,
    service: ExecutionTargetService = Depends(get_execution_target_service),
) -> ExecutionJobRead:
    return await service.get_job(job_id)


@worker_router.post("/{target_id}/heartbeat", response_model=ExecutionTargetRead)
async def heartbeat_execution_target(
    target_id: str,
    request: WorkerHeartbeatRequest,
    service: ExecutionTargetService = Depends(get_execution_target_service),
    x_worker_token: str | None = Header(default=None, alias="X-Worker-Token"),
) -> ExecutionTargetRead:
    target = await service._require_target(target_id)
    validate_worker_secret(target, x_worker_token)
    return await service.heartbeat(target_id=target_id, request=request)


@worker_router.post("/{target_id}/jobs/claim", response_model=WorkerJobClaimResponse)
async def claim_execution_job(
    target_id: str,
    request: WorkerClaimRequest,
    service: ExecutionTargetService = Depends(get_execution_target_service),
    x_worker_token: str | None = Header(default=None, alias="X-Worker-Token"),
) -> WorkerJobClaimResponse:
    target = await service._require_target(target_id)
    validate_worker_secret(target, x_worker_token)
    job = await service.claim_job(target_id=target_id, request=request)
    return WorkerJobClaimResponse(job=job)


@worker_router.post("/{target_id}/jobs/{job_id}/complete", response_model=ExecutionJobRead)
async def complete_execution_job(
    target_id: str,
    job_id: str,
    request: WorkerJobCompleteRequest,
    service: ExecutionTargetService = Depends(get_execution_target_service),
    x_worker_token: str | None = Header(default=None, alias="X-Worker-Token"),
) -> ExecutionJobRead:
    target = await service._require_target(target_id)
    validate_worker_secret(target, x_worker_token)
    return await service.complete_job(target_id=target_id, job_id=job_id, request=request)


@worker_router.post("/{target_id}/jobs/{job_id}/fail", response_model=ExecutionJobRead)
async def fail_execution_job(
    target_id: str,
    job_id: str,
    request: WorkerJobFailRequest,
    service: ExecutionTargetService = Depends(get_execution_target_service),
    x_worker_token: str | None = Header(default=None, alias="X-Worker-Token"),
) -> ExecutionJobRead:
    target = await service._require_target(target_id)
    validate_worker_secret(target, x_worker_token)
    return await service.fail_job(target_id=target_id, job_id=job_id, request=request)


@worker_router.post("/{target_id}/jobs/{job_id}/requeue", response_model=ExecutionJobRead)
async def requeue_execution_job(
    target_id: str,
    job_id: str,
    request: WorkerJobRequeueRequest,
    service: ExecutionTargetService = Depends(get_execution_target_service),
    x_worker_token: str | None = Header(default=None, alias="X-Worker-Token"),
) -> ExecutionJobRead:
    target = await service._require_target(target_id)
    validate_worker_secret(target, x_worker_token)
    return await service.requeue_job(target_id=target_id, job_id=job_id, request=request)
