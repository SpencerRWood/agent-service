import asyncio
from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.platform.agent_tasks.schemas import (
    AgentTaskCreateRequest,
    AgentTaskEnvelope,
    BackendName,
    TaskClass,
    TaskState,
    WorkerDispatchDecision,
)
from app.platform.agent_tasks.service import AgentTaskService
from app.platform.approvals.schemas import ApprovalDecisionRead, ApprovalRequestRead
from app.platform.artifacts.schemas import ArtifactRead
from app.platform.events.schemas import EventRead
from app.platform.execution_targets.schemas import ExecutionJobRead, ExecutionTargetRead
from app.platform.runs.schemas import RunRead, RunStepRead


class FakeRunService:
    def __init__(self) -> None:
        self.create_run_calls = 0
        self.create_step_calls = 0
        self.runs: dict[str, RunRead] = {
            "task-1": _build_run_read("task-1", status="queued"),
        }
        self.steps_by_run: dict[str, list[RunStepRead]] = {
            "task-1": [_build_step_read("task-1", "step-1", step_type="implement", input_json={})],
        }
        self.recent_steps: list[RunStepRead] = []

    async def create_run(self, request):
        del request
        self.create_run_calls += 1
        run_id = f"task-{self.create_run_calls}"
        run = _build_run_read(run_id, status="queued")
        self.runs[run_id] = run
        return run

    async def create_step(self, run_id, request):
        self.create_step_calls += 1
        step = _build_step_read(
            run_id,
            f"step-{self.create_step_calls}",
            step_type=request.step_type,
            input_json=request.input,
        )
        self.steps_by_run[run_id] = [step]
        self.recent_steps.insert(0, step)
        return step

    async def get_run(self, run_id):
        return self.runs[run_id]

    async def list_steps(self, run_id):
        return self.steps_by_run[run_id]

    async def list_recent_steps(self, *, limit=50):
        return self.recent_steps[:limit]

    async def update_run_status(self, run_id, status_value):
        run = self.runs[run_id]
        updated = run.model_copy(update={"status": status_value})
        self.runs[run_id] = updated
        return updated

    async def update_step_status(self, step_id, *, status_value, output=None):
        for _run_id, steps in self.steps_by_run.items():
            for index, step in enumerate(steps):
                if step.id != step_id:
                    continue
                updated_output = step.output_json or {}
                if output is not None:
                    updated_output = {**updated_output, **output}
                updated = step.model_copy(
                    update={"status": status_value, "output_json": updated_output}
                )
                steps[index] = updated
                if self.recent_steps and self.recent_steps[0].id == step.id:
                    self.recent_steps[0] = updated
                return updated
        raise AssertionError(f"Unknown step {step_id} for run update")


class FakeEventService:
    def __init__(self) -> None:
        self.events = []

    async def create(self, request):
        self.events.append(request)
        return EventRead(
            id="event-1",
            run_id="task-1",
            run_step_id="step-1",
            entity_type="agent_task",
            entity_id="task-1",
            event_type=request.event_type,
            payload_json=request.payload,
            actor_type=request.actor_type,
            actor_id=request.actor_id,
            trace_id=request.trace_id,
            created_at="2026-04-10T00:00:00Z",
        )

    async def list_for_run(self, run_id):
        del run_id
        return []


class FakeArtifactService:
    async def create(self, request):
        return ArtifactRead(
            id="artifact-1",
            run_id=request.run_id,
            run_step_id=request.run_step_id,
            artifact_type=request.artifact_type,
            title=request.title,
            content_json=request.content,
            uri=request.uri,
            provenance_json=request.provenance,
            status=request.status,
            created_at="2026-04-10T00:00:00Z",
        )

    async def list_for_run(self, run_id):
        del run_id
        return []


class FakeApprovalService:
    async def list_for_run(self, run_id):
        del run_id
        return [
            ApprovalRequestRead(
                id="approval-1",
                run_id="task-1",
                run_step_id="step-1",
                target_type="pull_request",
                target_id="pr-123",
                status="pending",
                decision_type="yes_no",
                policy_key="pr_review",
                reason="Approve the implementation PR",
                request_payload_json={"pr_number": 123},
                expires_at=None,
                created_at="2026-04-10T00:00:00Z",
                updated_at="2026-04-10T00:00:00Z",
            )
        ]

    async def list_decisions_for_run(self, run_id):
        del run_id
        return [
            ApprovalDecisionRead(
                id="decision-1",
                approval_request_id="approval-1",
                decision="approved",
                decided_by="reviewer-b",
                comment="looks good",
                decision_payload_json={"source": "openwebui"},
                created_at="2026-04-10T00:01:00Z",
            )
        ]


class FakeExecutionTargetService:
    async def choose_target(self, **kwargs):
        del kwargs
        return ExecutionTargetRead(
            id="worker-b",
            display_name="Worker B",
            executor_type="worker_agent",
            host=None,
            port=None,
            user_name=None,
            repo_root=None,
            labels_json=["mac"],
            supported_tools_json=["agent.run_task"],
            metadata_json={},
            secret_ref=None,
            enabled=True,
            is_default=True,
            last_seen_at=None,
            created_at="2026-04-10T00:00:00Z",
            updated_at="2026-04-10T00:00:00Z",
        )

    async def create_job(self, **kwargs):
        return ExecutionJobRead(
            id=kwargs["job_id"],
            target_id=kwargs["target_id"],
            tool_name=kwargs["tool_name"],
            status="queued",
            payload_json=kwargs["payload"],
            result_json=None,
            error_json=None,
            claimed_by=None,
            created_at="2026-04-10T00:00:00Z",
            claimed_at=None,
            completed_at=None,
        )

    async def wait_for_job(self, job_id):
        raise AssertionError(f"wait_for_job should not be called for {job_id}")

    async def get_job(self, job_id):
        del job_id
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution job not found")


def test_create_task_builds_envelope_with_worker_dispatch_and_broker_hints():
    run_service = FakeRunService()
    service = AgentTaskService(
        run_service=run_service,
        event_service=FakeEventService(),
        approval_service=FakeApprovalService(),
        artifact_service=FakeArtifactService(),
        execution_target_service=FakeExecutionTargetService(),
    )

    response = asyncio.run(
        service.create_task(
            AgentTaskCreateRequest(
                task_class=TaskClass.IMPLEMENT,
                prompt="Implement explicit routing",
                repo="agent-service",
            )
        )
    )

    assert response.task.task_id == "task-1"
    assert response.task.state == TaskState.QUEUED
    assert response.task.job is not None
    assert response.task.job.id == "task-1"
    assert response.task.envelope.dispatch.target_id == "worker-b"
    assert response.task.envelope.preferred_backend == BackendName.CODEX
    assert response.task.approvals[0].id == "approval-1"
    assert response.task.approval_decisions[0].id == "decision-1"
    assert run_service.create_run_calls == 1


def test_create_task_reuses_recent_duplicate_by_idempotency_key():
    run_service = FakeRunService()
    duplicate_envelope = AgentTaskEnvelope(
        task_id="task-existing",
        run_id="task-existing",
        step_id="step-existing",
        correlation_id="corr-existing",
        user_prompt="Plan the rollout",
        normalized_goal="Plan the rollout",
        task_class=TaskClass.PLAN_ONLY,
        public_agent_id="planner",
        runtime_key="planner_runtime",
        target_repo=None,
        target_branch=None,
        allowed_backends=[BackendName.LOCAL_LLM],
        preferred_backend=BackendName.LOCAL_LLM,
        approval_policy={"mode": "none"},
        timeout_policy={"seconds": 900},
        return_artifacts=["summary"],
        metadata={
            "idempotency_key": "retry-key-123",
            "idempotency_window_seconds": 900,
        },
        dispatch=WorkerDispatchDecision(
            target_id="worker-b",
            route_profile="cheap",
            reason="test duplicate",
        ),
    )
    run_service.runs["task-existing"] = _build_run_read("task-existing", status="queued")
    run_service.steps_by_run["task-existing"] = [
        _build_step_read(
            "task-existing",
            "step-existing",
            step_type="plan_only",
            input_json={
                "user_prompt": "Plan the rollout",
                "target_repo": None,
                "target_branch": None,
                "public_agent_id": "planner",
                "runtime_key": "planner_runtime",
                "metadata": {
                    "idempotency_key": "retry-key-123",
                    "idempotency_window_seconds": 900,
                },
            },
            output_json={"task_envelope": duplicate_envelope.model_dump(mode="json")},
        )
    ]
    run_service.recent_steps = list(run_service.steps_by_run["task-existing"])

    service = AgentTaskService(
        run_service=run_service,
        event_service=FakeEventService(),
        approval_service=FakeApprovalService(),
        artifact_service=FakeArtifactService(),
        execution_target_service=FakeExecutionTargetService(),
    )

    response = asyncio.run(
        service.create_task(
            AgentTaskCreateRequest(
                task_class=TaskClass.PLAN_ONLY,
                public_agent_id="planner",
                runtime_key="planner_runtime",
                prompt="Plan the rollout",
                metadata={
                    "idempotency_key": "retry-key-123",
                    "idempotency_window_seconds": 900,
                },
            )
        )
    )

    assert response.task.task_id == "task-existing"
    assert run_service.create_run_calls == 0


def _build_run_read(run_id: str, *, status: str) -> RunRead:
    now = datetime.now(UTC).isoformat()
    return RunRead(
        id=run_id,
        prompt_id=None,
        intent_id=None,
        status=status,
        started_at=None,
        completed_at=None,
        failed_at=None,
        created_at=now,
        updated_at=now,
    )


def _build_step_read(
    run_id: str,
    step_id: str,
    *,
    step_type: str,
    input_json: dict,
    output_json: dict | None = None,
) -> RunStepRead:
    now = datetime.now(UTC).isoformat()
    return RunStepRead(
        id=step_id,
        run_id=run_id,
        step_type=step_type,
        title=step_type,
        status="queued",
        sequence_index=0,
        input_json=input_json,
        output_json=output_json,
        approval_request_id=None,
        tool_invocation_id=None,
        artifact_id=None,
        started_at=None,
        completed_at=None,
        created_at=now,
    )
