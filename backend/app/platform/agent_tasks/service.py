from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
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
    PublicAgentTaskSummaryListRead,
    PublicAgentTaskSummaryRead,
    TaskClass,
    TaskState,
    WorkerDispatchDecision,
)
from app.platform.approvals.repository import ApprovalRepository
from app.platform.approvals.schemas import ApprovalDecisionCreate, ApprovalRequestCreate
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
        idempotency_key = _extract_idempotency_key(request.metadata)
        duplicate_task = await self._find_duplicate_task(
            request=request,
            task_class=task_class,
            idempotency_key=idempotency_key,
        )
        if duplicate_task is not None:
            return AgentTaskCreateResponse(task=duplicate_task)
        run, created_new = await self._run_service.create_or_get_run(
            RunCreate(
                status=TaskState.QUEUED.value,
                idempotency_key=idempotency_key,
            )
        )
        if idempotency_key and not created_new:
            existing_task = await self._wait_for_existing_task_read(
                run_id=run.id,
                request=request,
                task_class=task_class,
            )
            if existing_task is not None:
                return AgentTaskCreateResponse(task=existing_task)
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
                    "public_agent_id": request.public_agent_id,
                    "runtime_key": request.runtime_key,
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
            public_agent_id=request.public_agent_id,
            runtime_key=request.runtime_key,
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
        await self._run_service.update_step_status(
            step.id,
            status_value=step.status,
            output={"task_envelope": envelope.model_dump(mode="json")},
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
                    "public_agent_id": request.public_agent_id,
                    "runtime_key": request.runtime_key,
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

        job = None
        if self._requires_approval(envelope):
            await self._approval_service.create_request(
                ApprovalRequestCreate(
                    run_id=run.id,
                    run_step_id=step.id,
                    target_type="agent_task",
                    target_id=run.id,
                    reason=f"Approve {task_class.value} task before worker execution.",
                    policy_key="agent_task_execution",
                    requested_decision={
                        "task_id": run.id,
                        "public_agent_id": envelope.public_agent_id,
                        "runtime_key": envelope.runtime_key,
                    },
                )
            )
            await self._run_service.update_run_status(run.id, TaskState.PENDING_APPROVAL.value)
            await self._run_service.update_step_status(
                step.id,
                status_value=TaskState.PENDING_APPROVAL.value,
            )
            await self._event_service.create(
                EventCreate(
                    run_id=run.id,
                    run_step_id=step.id,
                    entity_type="agent_task",
                    entity_id=run.id,
                    event_type="agent.task.awaiting_approval",
                    payload={
                        "state": TaskState.PENDING_APPROVAL.value,
                        "public_agent_id": envelope.public_agent_id,
                        "runtime_key": envelope.runtime_key,
                        "message": "Task is waiting for approval before dispatch.",
                    },
                    actor_type="broker",
                    actor_id="agent-services",
                    trace_id=correlation_id,
                )
            )
        else:
            job = await self._dispatch_task(envelope)
        if request.wait_for_completion and job is not None:
            job = await self._execution_target_service.wait_for_job(job.id)
        return AgentTaskCreateResponse(
            task=await self._build_task_read(run.id, envelope=envelope, job=job)
        )

    async def get_task(self, task_id: str) -> AgentTaskRead:
        return await self._build_task_read(task_id)

    async def list_public_tasks(self, *, limit: int = 25) -> PublicAgentTaskSummaryListRead:
        runs = await self._run_service.list_recent_runs(limit=limit)
        items = []
        for run in runs:
            try:
                task = await self._build_task_read(run.id)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_404_NOT_FOUND:
                    continue
                raise
            items.append(_to_public_task_summary(task))
        return PublicAgentTaskSummaryListRead(items=items)

    async def approve_task(
        self,
        task_id: str,
        *,
        decided_by: str | None = None,
        comment: str | None = None,
    ) -> AgentTaskRead:
        task = await self._build_task_read(task_id)
        approval = _pending_approval_for_task(task)
        if approval is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Task does not have a pending approval request.",
            )
        await self._approval_service.create_decision(
            approval.id,
            ApprovalDecisionCreate(
                decision="approved",
                decided_by=decided_by,
                comment=comment,
            ),
        )
        await self._run_service.update_run_status(task.run.id, TaskState.QUEUED.value)
        await self._run_service.update_step_status(
            task.step.id,
            status_value=TaskState.QUEUED.value,
        )
        await self._event_service.create(
            EventCreate(
                run_id=task.run.id,
                run_step_id=task.step.id,
                entity_type="agent_task",
                entity_id=task_id,
                event_type="agent.task.approved",
                payload={
                    "state": TaskState.QUEUED.value,
                    "message": "Task approved and queued for worker dispatch.",
                },
                actor_type="user",
                actor_id=decided_by,
                trace_id=task.envelope.correlation_id,
            )
        )
        if task.job is None:
            await self._dispatch_task(task.envelope)
        return await self._build_task_read(task_id)

    async def reject_task(
        self,
        task_id: str,
        *,
        decided_by: str | None = None,
        comment: str | None = None,
    ) -> AgentTaskRead:
        task = await self._build_task_read(task_id)
        approval = _pending_approval_for_task(task)
        if approval is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Task does not have a pending approval request.",
            )
        await self._approval_service.create_decision(
            approval.id,
            ApprovalDecisionCreate(
                decision="rejected",
                decided_by=decided_by,
                comment=comment,
            ),
        )
        await self._run_service.update_run_status(task.run.id, TaskState.REJECTED.value)
        await self._run_service.update_step_status(
            task.step.id,
            status_value=TaskState.REJECTED.value,
            output={"rejected": True, "comment": comment},
        )
        await self._event_service.create(
            EventCreate(
                run_id=task.run.id,
                run_step_id=task.step.id,
                entity_type="agent_task",
                entity_id=task_id,
                event_type="agent.task.rejected",
                payload={
                    "state": TaskState.REJECTED.value,
                    "message": "Task approval was rejected.",
                },
                actor_type="user",
                actor_id=decided_by,
                trace_id=task.envelope.correlation_id,
            )
        )
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
                "public_agent_id": request.public_agent_id,
                "runtime_key": request.runtime_key,
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
            reason=(
                f"{request.execution_mode.value} selected worker '{target.id}' for "
                f"{request.public_agent_id or task_class.value}."
            ),
            debug={
                "request_backend": request.backend.value if request.backend else None,
                "selected_target": target.id,
                "public_agent_id": request.public_agent_id,
                "runtime_key": request.runtime_key,
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
            try:
                job = await self._execution_target_service.get_job(task_id)
            except HTTPException as exc:
                if exc.status_code != status.HTTP_404_NOT_FOUND:
                    raise
                job = None
        if envelope is None:
            try:
                if job is not None:
                    payload = job.payload_json["task"]
                else:
                    payload = ((step.output_json or {}).get("task_envelope")) or {}
                envelope = AgentTaskEnvelope.model_validate(payload)
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

    async def _dispatch_task(self, envelope: AgentTaskEnvelope):
        return await self._execution_target_service.create_job(
            target_id=envelope.dispatch.target_id,
            tool_name="agent.run_task",
            payload={"task": envelope.model_dump(mode="json")},
            job_id=envelope.run_id,
        )

    def _requires_approval(self, envelope: AgentTaskEnvelope) -> bool:
        return str(envelope.approval_policy.get("mode") or "none") == "required"

    async def _find_duplicate_task(
        self,
        *,
        request: AgentTaskCreateRequest,
        task_class: TaskClass,
        idempotency_key: str | None,
    ) -> AgentTaskRead | None:
        if not idempotency_key:
            return None

        existing_run = await self._run_service.get_run_by_idempotency_key(idempotency_key)
        if existing_run is not None:
            return await self._wait_for_existing_task_read(
                run_id=existing_run.id,
                request=request,
                task_class=task_class,
            )

        metadata = request.metadata or {}
        window_seconds = _coerce_idempotency_window_seconds(
            metadata.get("idempotency_window_seconds")
        )
        cutoff = datetime.now(UTC) - timedelta(seconds=window_seconds)
        recent_steps = await self._run_service.list_recent_steps(limit=50)
        for step in recent_steps:
            if step.created_at < cutoff:
                continue
            input_json = step.input_json or {}
            step_metadata = input_json.get("metadata") or {}
            if str(step_metadata.get("idempotency_key") or "").strip() != idempotency_key:
                continue
            if input_json.get("user_prompt") != request.prompt:
                continue
            if input_json.get("public_agent_id") != request.public_agent_id:
                continue
            if input_json.get("runtime_key") != request.runtime_key:
                continue
            if input_json.get("target_repo") != request.repo:
                continue
            if step.step_type != task_class.value:
                continue
            return await self._build_task_read(step.run_id)
        return None

    async def _wait_for_existing_task_read(
        self,
        *,
        run_id: str,
        request: AgentTaskCreateRequest,
        task_class: TaskClass,
    ) -> AgentTaskRead | None:
        for _attempt in range(10):
            try:
                task = await self._build_task_read(run_id)
            except HTTPException as exc:
                if exc.status_code != status.HTTP_404_NOT_FOUND:
                    raise
                task = None
            if task is not None and _task_matches_request(
                task, request=request, task_class=task_class
            ):
                return task
            await asyncio.sleep(0.05)
        return None


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


def _pending_approval_for_task(task: AgentTaskRead):
    for approval in task.approvals:
        if approval.status in {"pending", "requested"}:
            return approval
    return None


def _coerce_idempotency_window_seconds(value) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return 60
    return max(5, min(seconds, 3600))


def _extract_idempotency_key(metadata: dict | None) -> str | None:
    if not metadata:
        return None
    normalized = str(metadata.get("idempotency_key") or "").strip()
    return normalized or None


def _task_matches_request(
    task: AgentTaskRead,
    *,
    request: AgentTaskCreateRequest,
    task_class: TaskClass,
) -> bool:
    return (
        task.envelope.user_prompt == request.prompt
        and task.envelope.public_agent_id == request.public_agent_id
        and task.envelope.runtime_key == request.runtime_key
        and task.envelope.target_repo == request.repo
        and task.envelope.task_class == task_class
    )


def _to_public_task_summary(task: AgentTaskRead) -> PublicAgentTaskSummaryRead:
    approval_pending = any(
        approval.status in {"pending", "requested"} for approval in task.approvals
    )
    completed_at = (
        task.result.completed_at
        if task.result is not None and task.result.completed_at is not None
        else task.job.completed_at
        if task.job is not None
        else task.run.completed_at
    )
    duration_seconds = None
    if completed_at is not None:
        duration_seconds = max((completed_at - task.run.created_at).total_seconds(), 0.0)
    last_event_message = None
    for event in reversed(task.events):
        message = str(event.payload_json.get("message") or "").strip()
        if message:
            last_event_message = message
            break
    return PublicAgentTaskSummaryRead(
        task_id=task.task_id,
        agent_id=task.envelope.public_agent_id,
        runtime_key=task.envelope.runtime_key,
        task_class=task.envelope.task_class.value,
        state="pending_approval" if approval_pending else task.state.value,
        approval_pending=approval_pending,
        summary=task.result.summary if task.result is not None else None,
        prompt=task.envelope.user_prompt,
        execution_mode=task.envelope.execution_mode.value,
        preferred_backend=task.envelope.preferred_backend.value
        if task.envelope.preferred_backend is not None
        else None,
        selected_backend=task.result.backend.value if task.result and task.result.backend else None,
        target_id=task.envelope.dispatch.target_id,
        route_profile=task.envelope.dispatch.route_profile,
        created_at=task.run.created_at,
        completed_at=completed_at,
        duration_seconds=duration_seconds,
        last_event_message=last_event_message,
        stream_url=f"/api/agent-tasks/{task.task_id}/stream",
    )
