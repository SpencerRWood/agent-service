from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.features.orchestration.dependencies import get_orchestration_service
from app.features.orchestration.schemas import (
    ChatToolCreateRunRequest,
    ChatToolRunResponse,
    ChatToolStatusResponse,
    CreateRunRequest,
    PullRequestEventRequest,
    ReconcileResponse,
    RetryRunRequest,
    RunListResponse,
    RunRead,
)
from app.features.orchestration.service import OrchestrationService

router = APIRouter(prefix="/orchestration/runs", tags=["orchestration"])
tool_router = APIRouter(prefix="/orchestration/tools", tags=["orchestration-tools"])


@router.post("/", response_model=RunRead, status_code=201)
async def create_run(
    request: CreateRunRequest,
    service: OrchestrationService = Depends(get_orchestration_service),
) -> RunRead:
    return await service.create_run(request)


@router.get("/", response_model=RunListResponse)
async def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: OrchestrationService = Depends(get_orchestration_service),
) -> RunListResponse:
    return await service.list_runs(limit=limit, offset=offset)


@router.get("/{run_id}", response_model=RunRead)
async def get_run(
    run_id: str,
    service: OrchestrationService = Depends(get_orchestration_service),
) -> RunRead:
    return await service.get_run(run_id)


@router.post("/{run_id}/retry", response_model=RunRead)
async def retry_run(
    run_id: str,
    request: RetryRunRequest,
    service: OrchestrationService = Depends(get_orchestration_service),
) -> RunRead:
    return await service.retry_run(run_id, request.reason)


@router.post("/{run_id}/reconcile", response_model=ReconcileResponse)
async def reconcile_run(
    run_id: str,
    service: OrchestrationService = Depends(get_orchestration_service),
) -> ReconcileResponse:
    return await service.reconcile_run(run_id)


@router.post("/{run_id}/pull-request-events", response_model=RunRead)
async def apply_pull_request_event(
    run_id: str,
    request: PullRequestEventRequest,
    service: OrchestrationService = Depends(get_orchestration_service),
) -> RunRead:
    return await service.apply_pull_request_event(run_id, request)


@tool_router.post("/control-hub-chat/run", response_model=ChatToolRunResponse, status_code=201)
async def create_run_from_control_hub_chat(
    request: ChatToolCreateRunRequest,
    service: OrchestrationService = Depends(get_orchestration_service),
) -> ChatToolRunResponse:
    return await service.create_run_from_chat_tool(request)


@tool_router.get("/control-hub-chat/run/{run_id}", response_model=ChatToolStatusResponse)
async def get_control_hub_chat_run_status(
    run_id: str,
    service: OrchestrationService = Depends(get_orchestration_service),
) -> ChatToolStatusResponse:
    return await service.get_chat_tool_status(run_id)
