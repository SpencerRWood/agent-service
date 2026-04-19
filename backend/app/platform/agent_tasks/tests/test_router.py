from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.settings import settings
from app.platform.agent_tasks.router import (
    get_agent_task_service,
    get_task_store,
    router,
)
from app.platform.agent_tasks.schemas import (
    AgentTaskEnvelope,
    AgentTaskRead,
    AgentTaskResult,
    BackendName,
    ExecutionMode,
    PublicAgentTaskRead,
    PublicAgentTaskSummaryListRead,
    TaskArtifact,
    TaskState,
    WorkerDispatchDecision,
)
from app.platform.agent_tasks.task_store import TaskStore, to_public_task
from app.platform.approvals.schemas import ApprovalDecisionRead, ApprovalRequestRead
from app.platform.events.schemas import EventRead
from app.platform.runs.schemas import RunRead, RunStepRead


class FakeAgentTaskService:
    def __init__(self, task: AgentTaskRead | None = None) -> None:
        self.task = task or build_task(task_id="task-1")

    async def get_task(self, task_id: str) -> AgentTaskRead:
        assert task_id == self.task.task_id
        return self.task


class FakeTaskStore(TaskStore):
    def __init__(self) -> None:
        self.task = build_task(task_id="task-1")

    async def get_task(self, task_id: str) -> AgentTaskRead:
        assert task_id == self.task.task_id
        return self.task

    async def get_public_task(self, task_id: str) -> PublicAgentTaskRead:
        return to_public_task(await self.get_task(task_id))

    async def list_public_tasks(self, *, limit: int = 25) -> PublicAgentTaskSummaryListRead:
        del limit
        public_task = to_public_task(self.task)
        return PublicAgentTaskSummaryListRead(
            items=[
                {
                    "task_id": self.task.task_id,
                    "agent_id": self.task.envelope.public_agent_id,
                    "runtime_key": self.task.envelope.runtime_key,
                    "task_class": self.task.envelope.task_class.value,
                    "state": public_task.state,
                    "approval_pending": public_task.approval_pending,
                    "summary": None,
                    "prompt": self.task.envelope.user_prompt,
                    "execution_mode": self.task.envelope.execution_mode.value,
                    "preferred_backend": self.task.envelope.preferred_backend.value,
                    "selected_backend": None,
                    "target_id": self.task.envelope.dispatch.target_id,
                    "route_profile": self.task.envelope.dispatch.route_profile,
                    "created_at": self.task.run.created_at,
                    "completed_at": None,
                    "duration_seconds": None,
                    "last_event_message": "Waiting for approval.",
                    "stream_url": public_task.links.stream_url,
                }
            ]
        )

    async def approve_task(
        self,
        task_id: str,
        *,
        decided_by: str | None = None,
        comment: str | None = None,
    ) -> AgentTaskRead:
        del decided_by, comment
        assert task_id == self.task.task_id
        self.task.approvals[0].status = "approved"
        self.task.state = TaskState.QUEUED
        return self.task

    async def reject_task(
        self,
        task_id: str,
        *,
        decided_by: str | None = None,
        comment: str | None = None,
    ) -> AgentTaskRead:
        del decided_by, comment
        assert task_id == self.task.task_id
        self.task.approvals[0].status = "rejected"
        self.task.state = TaskState.REJECTED
        return self.task


def build_task(*, task_id: str) -> AgentTaskRead:
    return AgentTaskRead(
        task_id=task_id,
        state=TaskState.PENDING_APPROVAL,
        envelope=AgentTaskEnvelope(
            task_id=task_id,
            run_id=task_id,
            step_id="step-1",
            correlation_id="corr-1",
            user_prompt="Need approval status",
            normalized_goal="Need approval status",
            task_class="review",
            public_agent_id="reviewer",
            runtime_key="review_runtime",
            target_repo="agent-service",
            target_branch=None,
            execution_mode=ExecutionMode.OPENCODE,
            allowed_backends=[BackendName.CODEX],
            preferred_backend=BackendName.CODEX,
            approval_policy={"mode": "required"},
            timeout_policy={"seconds": 900},
            return_artifacts=["summary"],
            metadata={},
            dispatch=WorkerDispatchDecision(
                target_id="mbp-primary",
                route_profile="coding",
                reason="test",
            ),
        ),
        run=RunRead(
            id=task_id,
            prompt_id=None,
            intent_id=None,
            status="pending_approval",
            started_at=None,
            completed_at=None,
            failed_at=None,
            created_at="2026-04-10T00:00:00Z",
            updated_at="2026-04-10T00:00:00Z",
        ),
        step=RunStepRead(
            id="step-1",
            run_id=task_id,
            step_type="review",
            title="review",
            status="pending_approval",
            sequence_index=0,
            input_json={},
            output_json=None,
            approval_request_id="approval-1",
            tool_invocation_id=None,
            artifact_id=None,
            started_at=None,
            completed_at=None,
            created_at="2026-04-10T00:00:00Z",
        ),
        job=None,
        events=[
            EventRead(
                id="event-1",
                run_id=task_id,
                run_step_id="step-1",
                entity_type="agent_task",
                entity_id=task_id,
                event_type="agent.task.awaiting_approval",
                payload_json={"message": "Waiting for approval.", "state": "pending_approval"},
                actor_type="broker",
                actor_id="agent-services",
                trace_id="corr-1",
                created_at="2026-04-10T00:00:00Z",
            )
        ],
        approvals=[
            ApprovalRequestRead(
                id="approval-1",
                run_id=task_id,
                run_step_id="step-1",
                target_type="pull_request",
                target_id="pr-123",
                status="pending",
                decision_type="yes_no",
                policy_key="pr_review",
                reason="Approve PR #123",
                request_payload_json={"pr_number": 123},
                expires_at=None,
                created_at="2026-04-10T00:00:30Z",
                updated_at="2026-04-10T00:00:30Z",
            )
        ],
        approval_decisions=[
            ApprovalDecisionRead(
                id="decision-1",
                approval_request_id="approval-1",
                decision="approved",
                decided_by="reviewer-b",
                comment="approved",
                decision_payload_json={"source": "openwebui"},
                created_at="2026-04-10T00:01:00Z",
            )
        ],
        artifacts=[],
        result=None,
    )


def build_client(task_store: FakeTaskStore | None = None) -> TestClient:
    app = FastAPI()
    task_store = task_store or FakeTaskStore()
    service = FakeAgentTaskService(task_store.task)
    app.include_router(router, prefix=settings.api_prefix)
    app.dependency_overrides[get_agent_task_service] = lambda: service
    app.dependency_overrides[get_task_store] = lambda: task_store
    return TestClient(app)


def test_stream_agent_task_includes_approval_events_and_terminal_pending_approval():
    client = build_client()

    with client.stream("GET", "/api/agent-tasks/task-1/stream") as response:
        body = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text()
        )

    assert response.status_code == 200
    assert "event: approval\n" in body
    assert '"approval_id": "approval-1"' in body
    assert "event: terminal\n" in body
    assert '"status": "pending_approval"' in body


def test_stream_agent_task_emits_terminal_for_inline_completed_task():
    task_store = FakeTaskStore()
    inline_completed_task = build_task(task_id="task-inline")
    inline_completed_task.state = TaskState.COMPLETED
    inline_completed_task.run.status = "completed"
    inline_completed_task.run.completed_at = "2026-04-10T00:00:02Z"
    inline_completed_task.step.status = "completed"
    inline_completed_task.step.completed_at = "2026-04-10T00:00:02Z"
    inline_completed_task.approvals = []
    inline_completed_task.job = None
    inline_completed_task.result = AgentTaskResult(
        state=TaskState.COMPLETED,
        backend=BackendName.CODEX,
        execution_mode=ExecutionMode.OPENCODE,
        summary="Planner task completed inline.",
        artifacts=[
            TaskArtifact(
                artifact_type="summary",
                title="Plan",
                content={"markdown": "done"},
                provenance={},
            )
        ],
        completed_at="2026-04-10T00:00:02Z",
    )
    inline_completed_task.events = [
        EventRead(
            id="event-2",
            run_id="task-inline",
            run_step_id="step-1",
            entity_type="agent_task",
            entity_id="task-inline",
            event_type="agent.task.completed",
            payload_json={"message": "Planner task completed inline.", "state": "completed"},
            actor_type="broker",
            actor_id="agent-services",
            trace_id="corr-1",
            created_at="2026-04-10T00:00:02Z",
        )
    ]
    task_store.task = inline_completed_task
    client = build_client(task_store)

    with client.stream("GET", "/api/agent-tasks/task-inline/stream") as response:
        body = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text()
        )

    assert response.status_code == 200
    assert "event: terminal\n" in body
    assert '"status": "completed"' in body


def test_stream_agent_task_emits_terminal_for_inline_deferred_task():
    task_store = FakeTaskStore()
    inline_deferred_task = build_task(task_id="task-inline-deferred")
    inline_deferred_task.state = TaskState.DEFERRED_UNTIL_RESET
    inline_deferred_task.run.status = "deferred_until_reset"
    inline_deferred_task.run.completed_at = "2026-04-10T00:00:02Z"
    inline_deferred_task.step.status = "deferred_until_reset"
    inline_deferred_task.step.completed_at = "2026-04-10T00:00:02Z"
    inline_deferred_task.approvals = []
    inline_deferred_task.job = None
    inline_deferred_task.result = AgentTaskResult(
        state=TaskState.DEFERRED_UNTIL_RESET,
        backend=BackendName.LOCAL_LLM,
        execution_mode=ExecutionMode.OPENCODE,
        summary="No backend is currently available. Task deferred until reset.",
        artifacts=[],
        metrics={},
        completed_at="2026-04-10T00:00:02Z",
    )
    task_store.task = inline_deferred_task
    client = build_client(task_store)

    with client.stream("GET", "/api/agent-tasks/task-inline-deferred/stream") as response:
        body = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text()
        )

    assert response.status_code == 200
    assert "event: terminal\n" in body
    assert '"status": "deferred_until_reset"' in body


def test_get_agent_task_returns_compact_public_view():
    client = build_client()

    response = client.get("/api/agent-tasks/task-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_id"] == "reviewer"
    assert payload["state"] == "pending_approval"
    assert payload["approval_pending"] is True
    assert payload["links"]["approve_url"] == "/api/agent-tasks/task-1/approve"


def test_list_agent_tasks_returns_recent_summaries():
    client = build_client()

    response = client.get("/api/agent-tasks/")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["agent_id"] == "reviewer"
    assert payload["items"][0]["target_id"] == "mbp-primary"
    assert payload["items"][0]["stream_url"] == "/api/agent-tasks/task-1/stream"


def test_approve_agent_task_returns_updated_public_view():
    client = build_client()

    response = client.post(
        "/api/agent-tasks/task-1/approve",
        json={"decided_by": "open-webui", "comment": "Approved"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "queued"
    assert payload["approval_pending"] is False


def test_reject_agent_task_returns_rejected_public_view():
    client = build_client()

    response = client.post(
        "/api/agent-tasks/task-1/reject",
        json={"decided_by": "open-webui", "comment": "Rejected"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "rejected"
    assert payload["approval_pending"] is False
