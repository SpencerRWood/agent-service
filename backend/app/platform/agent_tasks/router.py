from __future__ import annotations

import asyncio
import json
from datetime import datetime

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
from app.platform.approvals.repository import ApprovalRepository
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
        approval_repository=ApprovalRepository(db),
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
        sent_approval_versions: set[str] = set()
        sent_approval_decision_ids: set[str] = set()
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
            for approval in task.approvals:
                approval_version = f"{approval.id}:{approval.updated_at.isoformat()}"
                if approval_version in sent_approval_versions:
                    continue
                sent_approval_versions.add(approval_version)
                yield (
                    "event: approval\n"
                    "data: "
                    f"{json.dumps({'type': 'approval_request', 'approval_id': approval.id, 'status': approval.status, 'target_type': approval.target_type, 'target_id': approval.target_id, 'reason': approval.reason, 'decision_type': approval.decision_type, 'policy_key': approval.policy_key, 'requested_decision': approval.request_payload_json, 'expires_at': approval.expires_at.isoformat() if approval.expires_at else None, 'updated_at': approval.updated_at.isoformat()})}\n\n"
                )
            for decision in task.approval_decisions:
                if decision.id in sent_approval_decision_ids:
                    continue
                sent_approval_decision_ids.add(decision.id)
                yield (
                    "event: approval_decision\n"
                    "data: "
                    f"{json.dumps({'type': 'approval_decision', 'decision_id': decision.id, 'approval_id': decision.approval_request_id, 'decision': decision.decision, 'decided_by': decision.decided_by, 'comment': decision.comment, 'payload': decision.decision_payload_json, 'created_at': decision.created_at.isoformat()})}\n\n"
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


@worker_router.post("/{task_id}/deferred", status_code=202)
async def mark_agent_task_deferred(
    task_id: str,
    request: dict,
    service: AgentTaskService = Depends(get_agent_task_service),
) -> dict[str, str]:
    available_at = request.get("available_at")
    parsed_available_at = (
        datetime.fromisoformat(str(available_at).replace("Z", "+00:00")) if available_at else None
    )
    await service.note_deferred(
        task_id=task_id,
        available_at=parsed_available_at,
        reason_code=str(request.get("reason_code") or "backend_unavailable"),
        backend=str(request.get("backend")) if request.get("backend") else None,
    )
    return {"status": "accepted"}
