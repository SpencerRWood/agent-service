from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.session import get_db
from app.platform.agent_tasks.links import build_task_action_url
from app.platform.agent_tasks.schemas import (
    AgentTaskCreateRequest,
    AgentTaskRead,
    PublicAgentTaskRead,
    PublicAgentTaskSummaryListRead,
    PublicTaskActionLinks,
)
from app.platform.agent_tasks.service import AgentTaskService, build_agent_task_service
from app.platform.approvals.repository import ApprovalRepository
from app.platform.artifacts.repository import ArtifactRepository
from app.platform.events.repository import EventRepository
from app.platform.execution_targets.repository import ExecutionTargetRepository
from app.platform.execution_targets.service import ExecutionTargetService
from app.platform.runs.repository import RunRepository


class TaskStore:
    def __init__(self, service: AgentTaskService) -> None:
        self._service = service

    async def create_task(self, request: AgentTaskCreateRequest):
        return await self._service.create_task(request)

    async def get_task(self, task_id: str) -> AgentTaskRead:
        return await self._service.get_task(task_id)

    async def approve_task(
        self,
        task_id: str,
        *,
        decided_by: str | None = None,
        comment: str | None = None,
    ) -> AgentTaskRead:
        return await self._service.approve_task(task_id, decided_by=decided_by, comment=comment)

    async def reject_task(
        self,
        task_id: str,
        *,
        decided_by: str | None = None,
        comment: str | None = None,
    ) -> AgentTaskRead:
        return await self._service.reject_task(task_id, decided_by=decided_by, comment=comment)

    async def get_public_task(self, task_id: str) -> PublicAgentTaskRead:
        return to_public_task(await self.get_task(task_id))

    async def list_public_tasks(self, *, limit: int = 25) -> PublicAgentTaskSummaryListRead:
        return await self._service.list_public_tasks(limit=limit)


def to_public_task(task: AgentTaskRead) -> PublicAgentTaskRead:
    approval_pending = any(
        approval.status in {"pending", "requested"} for approval in task.approvals
    )
    summary = task.result.summary if task.result is not None else None
    return PublicAgentTaskRead(
        task_id=task.task_id,
        agent_id=task.envelope.public_agent_id,
        runtime_key=task.envelope.runtime_key,
        state="pending_approval" if approval_pending else task.state.value,
        summary=summary,
        approval_pending=approval_pending,
        links=PublicTaskActionLinks(
            stream_url=build_task_action_url(task.task_id, "stream"),
            approve_url=build_task_action_url(task.task_id, "approve")
            if approval_pending
            else None,
            reject_url=build_task_action_url(task.task_id, "reject") if approval_pending else None,
        ),
    )


def get_task_store(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskStore:
    return TaskStore(
        build_agent_task_service(
            run_repository=RunRepository(db),
            event_repository=EventRepository(db),
            approval_repository=ApprovalRepository(db),
            artifact_repository=ArtifactRepository(db),
            execution_target_service=ExecutionTargetService(ExecutionTargetRepository(db)),
        )
    )
