from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.core.settings import settings
from app.platform.agent_tasks.enrichment import (
    EnrichmentTaskKind,
    classify_prompt_kind,
    extract_enrichment_payload,
    extract_parent_task_id,
)
from app.platform.agent_tasks.runtime import (
    OpenCodeProgressReporter,
    OpenCodeRuntime,
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
    BackendName,
    PublicAgentTaskSummaryListRead,
    PublicAgentTaskSummaryRead,
    TaskClass,
    TaskState,
    WorkerDispatchDecision,
    WorkflowOutcome,
)
from app.platform.agents.schemas import (
    AgentDefinition,
    AgentWorkflowActionDefinition,
    AgentWorkflowDefinition,
    AgentWorkflowStepDefinition,
)
from app.platform.agents.service import AgentRegistry, RuntimeRegistry, get_runtime_registry
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
        agent_registry: AgentRegistry | None = None,
        runtime_registry: RuntimeRegistry | None = None,
    ) -> None:
        self._run_service = run_service
        self._event_service = event_service
        self._approval_service = approval_service
        self._artifact_service = artifact_service
        self._execution_target_service = execution_target_service
        self._runtime_registry = runtime_registry or get_runtime_registry()
        self._agent_registry = agent_registry or AgentRegistry(self._runtime_registry)

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
                    "agent_system_prompt": request.agent_system_prompt,
                    "agent_workflow": request.agent_workflow,
                    "metadata": request.metadata,
                },
            ),
        )
        correlation_id = str(uuid4())
        dispatch = await self._route_request(request=request, task_class=task_class)
        allowed_backends = request.allowed_backends or default_allowed_backends_for_task(task_class)
        preferred_backend = (
            request.backend
            or _resolve_backend_from_hint(request.backend_hint, allowed_backends)
            or default_preferred_backend_for_task(task_class)
        )
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
            agent_system_prompt=request.agent_system_prompt,
            agent_workflow=request.agent_workflow,
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
        elif (
            envelope.execution_mode.value == "opencode"
            and envelope.task_class == TaskClass.PLAN_ONLY
        ):
            reporter = OpenCodeProgressReporter(
                task_id=envelope.task_id,
                run_id=envelope.run_id,
                step_id=envelope.step_id,
                correlation_id=envelope.correlation_id,
                base_url=settings.agent_services_base_url
                or f"http://{settings.app_host}:{settings.app_port}",
            )
            runtime = OpenCodeRuntime.from_settings()
            result = await runtime.execute(envelope, reporter)
            await self._run_service.update_run_status(envelope.task_id, TaskState.COMPLETED.value)
            await self._run_service.update_step_status(
                envelope.step_id,
                status_value=TaskState.COMPLETED.value,
                output={"result": result.model_dump(mode="json")},
            )
            return AgentTaskCreateResponse(
                task=await self._build_task_read(
                    envelope.task_id,
                    envelope=envelope,
                    job=None,
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
        runs = await self._run_service.list_recent_runs(limit=min(limit * 5, 200))
        items: list[PublicAgentTaskSummaryRead] = []
        items_by_id: dict[str, PublicAgentTaskSummaryRead] = {}
        pending_enrichment: dict[str, dict] = {}
        for run in runs:
            try:
                task = await self._build_task_read(run.id)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_404_NOT_FOUND:
                    continue
                raise
            kind = classify_prompt_kind(task.envelope.user_prompt)
            if kind != EnrichmentTaskKind.RESPONSE:
                parent_task_id = extract_parent_task_id(task.envelope.user_prompt)
                if parent_task_id is None:
                    continue
                enrichment = extract_enrichment_payload(
                    kind, task.result.summary if task.result else None
                )
                if not enrichment:
                    continue
                pending_enrichment[parent_task_id] = {
                    **pending_enrichment.get(parent_task_id, {}),
                    **enrichment,
                }
                if parent_task_id in items_by_id:
                    items_by_id[parent_task_id] = items_by_id[parent_task_id].model_copy(
                        update={
                            **pending_enrichment[parent_task_id],
                        }
                    )
                    items = [
                        items_by_id.get(item.task_id, item)
                        if item.task_id == parent_task_id
                        else item
                        for item in items
                    ]
                continue

            summary = _to_public_task_summary(task)
            if task.task_id in pending_enrichment:
                summary = summary.model_copy(update=pending_enrichment[task.task_id])
            items.append(summary)
            items_by_id[task.task_id] = summary
            if len(items) >= limit:
                break
        return PublicAgentTaskSummaryListRead(items=items[:limit])

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

    async def handle_completed_job(
        self,
        *,
        task_id: str,
        result_payload: dict,
    ) -> AgentTaskRead | None:
        try:
            result = AgentTaskResult.model_validate(result_payload)
        except ValidationError:
            return None
        if result.state != TaskState.COMPLETED:
            return None

        task = await self._build_task_read(task_id)
        try:
            transition_request = self._build_transition_request(task=task, result=result)
        except HTTPException:
            return None
        if transition_request is None:
            return None

        follow_up = await self.create_task(transition_request)
        await self._event_service.create(
            EventCreate(
                run_id=task.run.id,
                run_step_id=task.step.id,
                entity_type="agent_task",
                entity_id=task.task_id,
                event_type="agent.task.workflow.transitioned",
                payload={
                    "message": (
                        f"Spawned follow-up task for {transition_request.public_agent_id} "
                        f"from {task.envelope.public_agent_id or task.envelope.task_class.value}."
                    ),
                    "workflow_outcome": _classify_workflow_outcome(task=task, result=result),
                    "source_task_id": task.task_id,
                    "source_agent_id": task.envelope.public_agent_id,
                    "target_task_id": follow_up.task.task_id,
                    "target_agent_id": transition_request.public_agent_id,
                    "target_runtime_key": transition_request.runtime_key,
                },
                actor_type="broker",
                actor_id="agent-services",
                trace_id=task.envelope.correlation_id,
            )
        )
        return follow_up.task

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
        elif isinstance(step.output_json, dict) and step.output_json.get("result") is not None:
            result = AgentTaskResult.model_validate(step.output_json["result"])
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
            if (input_json.get("agent_system_prompt") or None) != request.agent_system_prompt:
                continue
            if (input_json.get("agent_workflow") or {}) != request.agent_workflow:
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

    def _build_transition_request(
        self,
        *,
        task: AgentTaskRead,
        result: AgentTaskResult,
    ) -> AgentTaskCreateRequest | None:
        workflow = _workflow_from_payload(task.envelope.agent_workflow)
        if workflow is None:
            return None

        current_step = _resolve_workflow_step(workflow=workflow, metadata=task.envelope.metadata)
        if current_step is None:
            return None

        outcome = _classify_workflow_outcome(task=task, result=result)
        transition = _transition_for_outcome(current_step=current_step, outcome=outcome)
        if transition is None:
            transition = _legacy_transition_from_workflow(workflow=workflow, outcome=outcome)
        if transition is None or transition.action == "finish":
            return None

        if transition.action != "handoff":
            return None

        handoff_to = str(transition.to or "").strip()
        if not handoff_to:
            return None

        max_iterations = _coerce_handoff_iterations(workflow.max_iterations)
        current_iteration = _coerce_handoff_iterations(
            task.envelope.metadata.get("workflow_iteration"),
            default=0,
        )
        if current_iteration >= max_iterations:
            return None

        target_agent = self._agent_registry.get_agent(handoff_to)
        target_runtime = self._runtime_registry.get_runtime(target_agent.runtime)
        handoff_prompt = _build_handoff_prompt(
            source_task=task,
            result=result,
            target_agent=target_agent,
            transition=transition,
        )
        target_workflow = target_agent.workflow
        metadata = {
            **task.envelope.metadata,
            "workflow_iteration": current_iteration + 1,
            "workflow_origin_task_id": str(
                task.envelope.metadata.get("workflow_origin_task_id") or task.task_id
            ),
            "workflow_previous_task_id": task.task_id,
            "workflow_previous_agent_id": task.envelope.public_agent_id,
            "handoff_parent_task_id": task.task_id,
            "handoff_parent_agent_id": task.envelope.public_agent_id,
            "handoff_target_agent_id": target_agent.id,
            "handoff_trigger": "workflow_transition",
            "workflow_step_id": _entry_step_id(target_workflow),
        }
        metadata["idempotency_scope"] = "workflow_handoff"
        metadata["idempotency_key"] = _handoff_idempotency_key(
            workflow_origin_task_id=str(metadata["workflow_origin_task_id"]),
            source_task_id=task.task_id,
            target_agent_id=target_agent.id,
            iteration=current_iteration + 1,
        )
        metadata["idempotency_window_seconds"] = 3600

        return AgentTaskCreateRequest(
            task_class=target_runtime.task_class,
            public_agent_id=target_agent.id,
            runtime_key=target_runtime.key,
            agent_system_prompt=target_agent.system_prompt,
            agent_workflow=target_workflow.model_dump(mode="json") if target_workflow else {},
            prompt=handoff_prompt,
            repo=task.envelope.target_repo,
            target_branch=task.envelope.target_branch,
            execution_mode=task.envelope.execution_mode,
            route_profile=target_runtime.route_profile,
            approval_policy={"mode": target_runtime.approval_mode},
            metadata=metadata,
            wait_for_completion=False,
        )


def build_agent_task_service(
    *,
    run_repository: RunRepository,
    event_repository: EventRepository,
    approval_repository: ApprovalRepository,
    artifact_repository: ArtifactRepository,
    execution_target_service: ExecutionTargetService,
    agent_registry: AgentRegistry | None = None,
    runtime_registry: RuntimeRegistry | None = None,
) -> AgentTaskService:
    return AgentTaskService(
        run_service=RunService(run_repository),
        event_service=EventService(event_repository),
        approval_service=ApprovalService(approval_repository),
        artifact_service=ArtifactService(artifact_repository),
        execution_target_service=execution_target_service,
        agent_registry=agent_registry,
        runtime_registry=runtime_registry,
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


def _coerce_handoff_iterations(value, *, default: int = 1) -> int:
    try:
        iterations = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, iterations)


def _handoff_idempotency_key(
    *,
    workflow_origin_task_id: str,
    source_task_id: str,
    target_agent_id: str,
    iteration: int,
) -> str:
    key_material = {
        "workflow_origin_task_id": workflow_origin_task_id,
        "source_task_id": source_task_id,
        "target_agent_id": target_agent_id,
        "iteration": iteration,
    }
    return hashlib.sha256(json.dumps(key_material, sort_keys=True).encode("utf-8")).hexdigest()


def _build_handoff_prompt(
    *,
    source_task: AgentTaskRead,
    result: AgentTaskResult,
    target_agent: AgentDefinition,
    transition: AgentWorkflowActionDefinition,
) -> str:
    handoff_summary_prompt = str(transition.prompt or "").strip()
    source_agent = source_task.envelope.public_agent_id or source_task.envelope.task_class.value
    sections = [
        f"Workflow handoff from {source_agent} to {target_agent.id}.",
        f"Parent task ID: {source_task.task_id}",
        f"Original request:\n{source_task.envelope.user_prompt}",
        f"Previous result:\n{result.summary}",
    ]
    if handoff_summary_prompt:
        sections.append(f"Handoff instructions:\n{handoff_summary_prompt}")
    return "\n\n".join(sections).strip()


def _workflow_from_payload(payload: dict) -> AgentWorkflowDefinition | None:
    if not payload:
        return None
    try:
        return AgentWorkflowDefinition.model_validate(payload)
    except ValidationError:
        return None


def _entry_step_id(workflow: AgentWorkflowDefinition | None) -> str | None:
    if workflow is None:
        return None
    if workflow.entry_step:
        return workflow.entry_step
    if workflow.steps:
        return workflow.steps[0].id
    return None


def _resolve_workflow_step(
    *,
    workflow: AgentWorkflowDefinition,
    metadata: dict,
) -> AgentWorkflowStepDefinition | None:
    step_id = str(metadata.get("workflow_step_id") or _entry_step_id(workflow) or "").strip()
    if not step_id:
        return None
    for step in workflow.steps:
        if step.id == step_id:
            return step
    return None


def _transition_for_outcome(
    *,
    current_step: AgentWorkflowStepDefinition,
    outcome: WorkflowOutcome,
) -> AgentWorkflowActionDefinition | None:
    if outcome == WorkflowOutcome.SUCCESS:
        return current_step.on_success
    if outcome == WorkflowOutcome.NEEDS_CHANGES:
        return current_step.on_needs_changes or current_step.on_failure
    return current_step.on_failure


def _legacy_transition_from_workflow(
    *,
    workflow: AgentWorkflowDefinition,
    outcome: WorkflowOutcome,
) -> AgentWorkflowActionDefinition | None:
    handoff_to = str(workflow.handoff_to or "").strip()
    if outcome in {WorkflowOutcome.FAILURE, WorkflowOutcome.NEEDS_CHANGES} and handoff_to:
        return AgentWorkflowActionDefinition(
            action="handoff",
            to=handoff_to,
            prompt=workflow.handoff_summary_prompt,
        )
    return None


def _classify_workflow_outcome(*, task: AgentTaskRead, result: AgentTaskResult) -> WorkflowOutcome:
    if result.workflow_outcome is not None:
        return result.workflow_outcome
    if result.state != TaskState.COMPLETED:
        return WorkflowOutcome.FAILURE

    summary = (result.summary or "").lower()
    failure_markers = (
        "tests failed",
        "test failed",
        "failing",
        "failed",
        "error",
        "errors",
        "exception",
        "regression",
        "does not",
        "did not",
        "unable",
        "fix needed",
        "recommended fix",
        "needs changes",
    )
    success_markers = (
        "tests passed",
        "all tests passed",
        "validated successfully",
        "review passed",
        "no issues found",
        "looks good",
        "completed successfully",
    )
    if any(marker in summary for marker in success_markers):
        return WorkflowOutcome.SUCCESS
    needs_changes_markers = (
        "needs changes",
        "recommended fix",
        "fix needed",
        "follow-up implementation",
    )
    if any(marker in summary for marker in needs_changes_markers):
        return WorkflowOutcome.NEEDS_CHANGES
    if any(marker in summary for marker in failure_markers):
        return WorkflowOutcome.FAILURE
    if task.envelope.task_class == TaskClass.REVIEW:
        return WorkflowOutcome.NEEDS_CHANGES
    return WorkflowOutcome.SUCCESS


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
        and task.envelope.agent_system_prompt == request.agent_system_prompt
        and task.envelope.agent_workflow == request.agent_workflow
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
        task_kind=EnrichmentTaskKind.RESPONSE.value,
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
        conversation_title=None,
        conversation_tags=[],
        follow_ups=[],
        stream_url=f"/api/agent-tasks/{task.task_id}/stream",
    )


def _resolve_backend_from_hint(
    backend_hint: str | None,
    allowed_backends: list[BackendName],
) -> BackendName | None:
    if not backend_hint:
        return None
    hint_lower = backend_hint.lower().strip()
    for backend in allowed_backends:
        if backend.value == hint_lower:
            return backend
    return None
