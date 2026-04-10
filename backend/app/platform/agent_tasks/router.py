from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.session import get_db
from app.platform.agent_tasks.schemas import (
    AgentTaskCreateRequest,
    AgentTaskCreateResponse,
    AgentTaskProgressCreate,
    AgentTaskRead,
)
from app.platform.agent_tasks.service import AgentTaskService, build_agent_task_service
from app.platform.artifacts.repository import ArtifactRepository
from app.platform.artifacts.schemas import ArtifactCreate
from app.platform.events.repository import EventRepository
from app.platform.execution_targets.repository import ExecutionTargetRepository
from app.platform.execution_targets.service import ExecutionTargetService
from app.platform.runs.repository import RunRepository

router = APIRouter(prefix="/agent-tasks", tags=["platform-agent-tasks"])
worker_router = APIRouter(prefix="/worker/agent-tasks", tags=["platform-worker-agent-tasks"])


def get_agent_task_service(db: AsyncSession = Depends(get_db)) -> AgentTaskService:
    return build_agent_task_service(
        run_repository=RunRepository(db),
        event_repository=EventRepository(db),
        artifact_repository=ArtifactRepository(db),
        execution_target_service=ExecutionTargetService(ExecutionTargetRepository(db)),
    )


@router.post("/", response_model=AgentTaskCreateResponse, status_code=201)
async def create_agent_task(
    request: AgentTaskCreateRequest,
    service: AgentTaskService = Depends(get_agent_task_service),
) -> AgentTaskCreateResponse:
    return await service.create_task(request)


@router.get("/{task_id}", response_model=AgentTaskRead)
async def get_agent_task(
    task_id: str,
    service: AgentTaskService = Depends(get_agent_task_service),
) -> AgentTaskRead:
    return await service.get_task(task_id)


@router.get("/{task_id}/stream")
async def stream_agent_task(
    task_id: str,
    service: AgentTaskService = Depends(get_agent_task_service),
) -> StreamingResponse:
    async def event_stream():
        sent_event_ids: set[str] = set()
        sent_artifact_ids: set[str] = set()
        while True:
            task = await service.get_task(task_id)
            for event in task.events:
                if event.id in sent_event_ids:
                    continue
                sent_event_ids.add(event.id)
                yield (
                    "event: progress\n"
                    f"data: {json.dumps({'type': event.event_type, 'payload': event.payload_json})}\n\n"
                )
            for artifact in task.artifacts:
                if artifact.id in sent_artifact_ids:
                    continue
                sent_artifact_ids.add(artifact.id)
                yield (
                    "event: artifact\n"
                    f"data: {json.dumps({'type': artifact.artifact_type, 'title': artifact.title})}\n\n"
                )
            if task.job and task.job.status in {"completed", "failed"}:
                yield (
                    "event: terminal\n"
                    f"data: {json.dumps({'status': task.job.status, 'task_id': task.task_id})}\n\n"
                )
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@worker_router.post("/{task_id}/progress", status_code=202)
async def publish_agent_task_progress(
    task_id: str,
    request: AgentTaskProgressCreate,
    service: AgentTaskService = Depends(get_agent_task_service),
) -> dict[str, str]:
    await service.publish_progress(task_id, request)
    return {"status": "accepted"}


@worker_router.post("/{task_id}/artifacts", status_code=201)
async def publish_agent_task_artifact(
    task_id: str,
    request: ArtifactCreate,
    service: AgentTaskService = Depends(get_agent_task_service),
) -> dict[str, str]:
    await service.publish_artifact(task_id, request)
    return {"status": "created"}
