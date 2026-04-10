from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException, status

from app.platform.agent_tasks.runtime import (
    available_route_profiles,
    default_backend_for_task,
    default_fallback_for_task,
)
from app.platform.agent_tasks.schemas import (
    AgentTaskCreateRequest,
    AgentTaskCreateResponse,
    AgentTaskEnvelope,
    AgentTaskProgressCreate,
    AgentTaskRead,
    AgentTaskResult,
    AgentTaskRoutingDecision,
    ExecutionPath,
)
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
        run_repository: RunRepository,
        event_service: EventService,
        artifact_service: ArtifactService,
        execution_target_service: ExecutionTargetService,
    ) -> None:
        self._run_service = run_service
        self._run_repository = run_repository
        self._event_service = event_service
        self._artifact_service = artifact_service
        self._execution_target_service = execution_target_service

    async def create_task(self, request: AgentTaskCreateRequest) -> AgentTaskCreateResponse:
        run = await self._run_service.create_run(RunCreate(status="queued"))
        step = await self._run_service.create_step(
            run.id,
            RunStepCreate(
                step_type=request.task_class.value,
                title=request.task_class.value.replace("_", " "),
                status="queued",
                sequence_index=0,
                input={
                    "prompt": request.prompt,
                    "repo": request.repo,
                    "project_path": request.project_path,
                    "context": request.context,
                },
            ),
        )
        trace_id = str(uuid4())
        routing = await self._route_request(request)
        envelope = AgentTaskEnvelope(
            task_id=run.id,
            run_id=run.id,
            step_id=step.id,
            trace_id=trace_id,
            task_class=request.task_class,
            prompt=request.prompt,
            repo=request.repo,
            project_path=request.project_path,
            context=request.context,
            routing=routing,
            source=request.source,
            approvals=request.approvals,
            branch_workflow=request.branch_workflow,
            usage_limits=request.usage_limits,
            final_artifact_policy=request.final_artifact_policy,
        )
        await self._event_service.create(
            EventCreate(
                run_id=run.id,
                run_step_id=step.id,
                entity_type="agent_task",
                entity_id=run.id,
                event_type="agent.task.created",
                payload={
                    "task_class": request.task_class.value,
                    "backend": routing.selected_backend.value,
                    "execution_path": routing.execution_path.value,
                    "target_id": routing.target_id,
                    "reason": routing.reason,
                },
                actor_type="broker",
                actor_id="agent-services",
                trace_id=trace_id,
            )
        )
        job = await self._execution_target_service.create_job(
            target_id=routing.target_id,
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
        await self._event_service.create(
            EventCreate(
                run_id=request.run_id,
                run_step_id=request.step_id,
                entity_type="agent_task",
                entity_id=task_id,
                event_type=request.event_type,
                payload={"message": request.message, **request.payload},
                actor_type=request.actor_type,
                actor_id=request.actor_id,
                trace_id=request.trace_id,
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

    async def _route_request(self, request: AgentTaskCreateRequest) -> AgentTaskRoutingDecision:
        selected_backend = request.backend or default_backend_for_task(request.task_class)
        fallback_backend = request.fallback_backend
        if (
            fallback_backend is None
            and (request.execution_path or ExecutionPath.OPENCODE) == ExecutionPath.OPENCODE
        ):
            fallback_backend = default_fallback_for_task(request.task_class)
        execution_path = request.execution_path or ExecutionPath.OPENCODE
        route_profile = request.route_profile
        if route_profile is None:
            route_profile = available_route_profiles(request.task_class)[0]

        target = await self._execution_target_service.choose_target(
            explicit_target_id=request.target_id,
            tool_name="agent.run_task",
            routing_context={
                "prompt": request.prompt,
                "task_class": request.task_class.value,
                "route_profile": route_profile,
                "backend": selected_backend.value,
                "execution_path": execution_path.value,
            },
        )
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No execution target is available for agent.run_task.",
            )

        return AgentTaskRoutingDecision(
            execution_path=execution_path,
            selected_backend=selected_backend,
            fallback_backend=(None if execution_path == ExecutionPath.DIRECT else fallback_backend),
            target_id=target.id,
            route_profile=route_profile,
            reason=(
                f"{execution_path.value} selected {selected_backend.value} for "
                f"{request.task_class.value}."
            ),
            debug={
                "request_backend": request.backend.value if request.backend else None,
                "request_fallback_backend": (
                    request.fallback_backend.value if request.fallback_backend else None
                ),
                "request_execution_path": (
                    request.execution_path.value if request.execution_path else None
                ),
                "supported_route_profiles": list(available_route_profiles(request.task_class)),
                "selected_target": target.id,
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
        artifacts = await self._artifact_service.list_for_run(task_id)
        result = None
        if job.result_json is not None:
            result = AgentTaskResult.model_validate(job.result_json)
        return AgentTaskRead(
            task_id=task_id,
            envelope=envelope,
            run=run,
            step=step,
            job=job,
            events=events,
            artifacts=artifacts,
            result=result,
        )


def build_agent_task_service(
    *,
    run_repository: RunRepository,
    event_repository: EventRepository,
    artifact_repository: ArtifactRepository,
    execution_target_service: ExecutionTargetService,
) -> AgentTaskService:
    return AgentTaskService(
        run_service=RunService(run_repository),
        run_repository=run_repository,
        event_service=EventService(event_repository),
        artifact_service=ArtifactService(artifact_repository),
        execution_target_service=execution_target_service,
    )
