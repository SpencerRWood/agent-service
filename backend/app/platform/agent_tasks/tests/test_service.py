import asyncio

from app.platform.agent_tasks.schemas import (
    AgentTaskCreateRequest,
    BackendName,
    TaskClass,
    TaskState,
)
from app.platform.agent_tasks.service import AgentTaskService
from app.platform.artifacts.schemas import ArtifactRead
from app.platform.events.schemas import EventRead
from app.platform.execution_targets.schemas import ExecutionJobRead, ExecutionTargetRead
from app.platform.runs.schemas import RunRead, RunStepRead


class FakeRunService:
    async def create_run(self, request):
        del request
        return RunRead(
            id="task-1",
            prompt_id=None,
            intent_id=None,
            status="queued",
            started_at=None,
            completed_at=None,
            failed_at=None,
            created_at="2026-04-10T00:00:00Z",
            updated_at="2026-04-10T00:00:00Z",
        )

    async def create_step(self, run_id, request):
        del run_id, request
        return RunStepRead(
            id="step-1",
            run_id="task-1",
            step_type="implement",
            title="implement",
            status="queued",
            sequence_index=0,
            input_json={},
            output_json=None,
            approval_request_id=None,
            tool_invocation_id=None,
            artifact_id=None,
            started_at=None,
            completed_at=None,
            created_at="2026-04-10T00:00:00Z",
        )

    async def get_run(self, run_id):
        del run_id
        return await self.create_run(None)

    async def list_steps(self, run_id):
        del run_id
        return [await self.create_step("", None)]

    async def update_run_status(self, run_id, status_value):
        del run_id, status_value
        return await self.create_run(None)

    async def update_step_status(self, step_id, *, status_value, output=None):
        del step_id, status_value, output
        return await self.create_step("", None)


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
        raise AssertionError("get_job should not be called in this test")


def test_create_task_builds_envelope_with_worker_dispatch_and_broker_hints():
    service = AgentTaskService(
        run_service=FakeRunService(),
        event_service=FakeEventService(),
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
