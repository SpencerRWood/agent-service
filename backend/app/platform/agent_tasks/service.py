from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException, status

from app.platform.agent_tasks.runtime import (
    available_route_profiles,
    classify_task,
    default_allowed_backends_for_task,
    default_preferred_backend_for_task,
    normalize_goal,
)
from app.platform.agent_tasks.schemas import (
    AgentTaskCreateRequest,
    AgentTaskCreateResponse,
    AgentTaskEnvelope,
    AgentTaskProgressCreate,
    AgentTaskRead,
    AgentTaskResult,
    TaskState,
    WorkerDispatchDecision,
)
from app.platform.approvals.repository import ApprovalRepository
from app.platform.approvals.service import ApprovalService
from app.platform.artifacts.repository import ArtifactRepository
from app.platform.artifacts.schemas import ArtifactCreate
from app.platform.artifacts.service import ArtifactService
from app.platform.events.repository import EventRepository
from app.platform.events.schemas import EventCreate
from app.platform.events.service import EventService
from app.platform.execution_targets.service import ExecutionTargetService
from app.platform.runs.repository import RunRepository
from app.platform.runs.schemas import RunCreate, RunStepCreate
from app.platform.runs.service import RunService


class AgentTaskService:
    def __init__(
        self,
        *,
        run_service: RunService,
        event_service: EventService,
        approval_service: ApprovalService,
        artifact_service: ArtifactService,
        execution_target_service: ExecutionTargetService,
    ) -> None:
        self._run_service = run_service
        self._event_service = event_service
        self._approval_service = approval_service
        self._artifact_service = artifact_service
        self._execution_target_service = execution_target_service

    async def create_task(self, request: AgentTaskCreateRequest) -> AgentTaskCreateResponse:
        task_class = request.task_class or classify_task(request.prompt)
        run = await self._run_service.create_run(RunCreate(status=TaskState.QUEUED.value))
        step = await self._run_service.create_step(
            run.id,
            RunStepCreate(
                step_type=task_class.value,
                title=task_class.value.replace("_", " "),
                status=TaskState.QUEUED.value,
                sequence_index=0,
                input={
                    "user_prompt": request.prompt,
                    "target_repo": request.repo,
                    "target_branch": request.target_branch,
                    "metadata": request.metadata,
                },
            ),
        )
        correlation_id = str(uuid4())
        dispatch = await self._route_request(request=request, task_class=task_class)
        allowed_backends = request.allowed_backends or default_allowed_backends_for_task(task_class)
        preferred_backend = request.backend or default_preferred_backend_for_task(task_class)
        if preferred_backend not in allowed_backends:
            preferred_backend = allowed_backends[0]

        envelope = AgentTaskEnvelope(
            task_id=run.id,
            run_id=run.id,
            step_id=step.id,
            correlation_id=correlation_id,
            user_prompt=request.prompt,
            normalized_goal=normalize_goal(request.prompt),
            task_class=task_class,
            target_repo=request.repo,
            target_branch=request.target_branch,
            execution_mode=request.execution_mode,
            allowed_backends=allowed_backends,
            preferred_backend=preferred_backend,
            approval_policy=request.approval_policy or {"mode": "none"},
            timeout_policy=request.timeout_policy or {"seconds": 900},
            return_artifacts=request.return_artifacts,
            metadata=request.metadata,
            dispatch=dispatch,
        )

        await self._event_service.create(
            EventCreate(
                run_id=run.id,
                run_step_id=step.id,
                entity_type="agent_task",
                entity_id=run.id,
                event_type="agent.task.created",
                payload={
                    "state": TaskState.QUEUED.value,
                    "task_class": task_class.value,
                    "normalized_goal": envelope.normalized_goal,
                    "preferred_backend": preferred_backend.value,
                    "allowed_backends": [backend.value for backend in allowed_backends],
                    "execution_mode": envelope.execution_mode.value,
                    "dispatch_target": dispatch.target_id,
                    "dispatch_reason": dispatch.reason,
                },
                actor_type="broker",
                actor_id="agent-services",
                trace_id=correlation_id,
            )
        )

        job = await self._execution_target_service.create_job(
            target_id=dispatch.target_id,
            tool_name="agent.run_task",
            payload={"task": envelope.model_dump(mode="json")},
            job_id=run.id,
        )
        if request.wait_for_completion:
            job = await self._execution_target_service.wait_for_job(job.id)
        return AgentTaskCreateResponse(
            task=await self._build_task_read(run.id, envelope=envelope, job=job)
        )

    async def get_task(self, task_id: str) -> AgentTaskRead:
        return await self._build_task_read(task_id)

    async def publish_progress(self, task_id: str, request: AgentTaskProgressCreate) -> None:
        if request.state is not None:
            await self._run_service.update_run_status(request.run_id, request.state.value)
            await self._run_service.update_step_status(
                request.step_id,
                status_value=request.state.value,
            )
        await self._event_service.create(
            EventCreate(
                run_id=request.run_id,
                run_step_id=request.step_id,
                entity_type="agent_task",
                entity_id=task_id,
                event_type=request.event_type,
                payload={
                    "message": request.message,
                    "state": request.state.value if request.state is not None else None,
                    **request.payload,
                },
                actor_type=request.actor_type,
                actor_id=request.actor_id,
                trace_id=request.correlation_id,
            )
        )

    async def publish_artifact(self, task_id: str, artifact: ArtifactCreate) -> None:
        await self._artifact_service.create(artifact)
        await self._event_service.create(
            EventCreate(
                run_id=artifact.run_id,
                run_step_id=artifact.run_step_id,
                entity_type="agent_task",
                entity_id=task_id,
                event_type="agent.task.artifact.created",
                payload={
                    "artifact_type": artifact.artifact_type,
                    "title": artifact.title,
                    "status": artifact.status,
                },
                actor_type="worker",
                actor_id="worker-node",
            )
        )

    async def note_deferred(
        self,
        *,
        task_id: str,
        available_at: datetime | None,
        reason_code: str,
        backend: str | None,
    ) -> None:
        task = await self._build_task_read(task_id)
        await self._run_service.update_run_status(task.run.id, TaskState.DEFERRED_UNTIL_RESET.value)
        await self._run_service.update_step_status(
            task.step.id,
            status_value=TaskState.DEFERRED_UNTIL_RESET.value,
            output={
                "reason_code": reason_code,
                "backend": backend,
                "available_at": available_at.isoformat() if available_at is not None else None,
            },
        )
        await self._event_service.create(
            EventCreate(
                run_id=task.run.id,
                run_step_id=task.step.id,
                entity_type="agent_task",
                entity_id=task_id,
                event_type="agent.task.deferred",
                payload={
                    "state": TaskState.DEFERRED_UNTIL_RESET.value,
                    "reason_code": reason_code,
                    "backend": backend,
                    "available_at": available_at.isoformat() if available_at is not None else None,
                    "user_status": "Task deferred until backend reset window.",
                },
                actor_type="broker",
                actor_id="agent-services",
                trace_id=task.envelope.correlation_id,
            )
        )

    async def _route_request(
        self,
        *,
        request: AgentTaskCreateRequest,
        task_class,
    ) -> WorkerDispatchDecision:
        route_profile = request.route_profile or available_route_profiles(task_class)[0]
        target = await self._execution_target_service.choose_target(
            explicit_target_id=request.target_id,
            tool_name="agent.run_task",
            routing_context={
                "prompt": request.prompt,
                "task_class": task_class.value,
                "route_profile": route_profile,
                "execution_mode": request.execution_mode.value,
            },
        )
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No execution target is available for agent.run_task.",
            )
        return WorkerDispatchDecision(
            target_id=target.id,
            route_profile=route_profile,
            reason=f"{request.execution_mode.value} selected worker '{target.id}' for {task_class.value}.",
            debug={
                "request_backend": request.backend.value if request.backend else None,
                "selected_target": target.id,
                "supported_route_profiles": list(available_route_profiles(task_class)),
            },
        )

    async def _build_task_read(
        self,
        task_id: str,
        *,
        envelope: AgentTaskEnvelope | None = None,
        job=None,
    ) -> AgentTaskRead:
        run = await self._run_service.get_run(task_id)
        steps = await self._run_service.list_steps(task_id)
        if not steps:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task step not found")
        step = steps[0]
        if job is None:
            job = await self._execution_target_service.get_job(task_id)
        if envelope is None:
            try:
                envelope = AgentTaskEnvelope.model_validate(job.payload_json["task"])
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Stored task envelope is invalid.",
                ) from exc
        events = await self._event_service.list_for_run(task_id)
        approvals = await self._approval_service.list_for_run(task_id)
        approval_decisions = await self._approval_service.list_decisions_for_run(task_id)
        artifacts = await self._artifact_service.list_for_run(task_id)
        result = None
        if job is not None and job.result_json is not None:
            result = AgentTaskResult.model_validate(job.result_json)
        return AgentTaskRead(
            task_id=task_id,
            state=TaskState(run.status),
            envelope=envelope,
            run=run,
            step=step,
            job=job,
            events=events,
            approvals=approvals,
            approval_decisions=approval_decisions,
            artifacts=artifacts,
            result=result,
        )


def build_agent_task_service(
    *,
    run_repository: RunRepository,
    event_repository: EventRepository,
    approval_repository: ApprovalRepository,
    artifact_repository: ArtifactRepository,
    execution_target_service: ExecutionTargetService,
) -> AgentTaskService:
    return AgentTaskService(
        run_service=RunService(run_repository),
        event_service=EventService(event_repository),
        approval_service=ApprovalService(approval_repository),
        artifact_service=ArtifactService(artifact_repository),
        execution_target_service=execution_target_service,
    )
