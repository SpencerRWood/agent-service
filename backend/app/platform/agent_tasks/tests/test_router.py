from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.settings import settings
from app.platform.agent_tasks.router import get_agent_task_service, router
from app.platform.agent_tasks.schemas import (
    AgentTaskEnvelope,
    AgentTaskRead,
    BackendName,
    ExecutionMode,
    TaskState,
    WorkerDispatchDecision,
)
from app.platform.approvals.schemas import ApprovalDecisionRead, ApprovalRequestRead
from app.platform.events.schemas import EventRead
from app.platform.execution_targets.schemas import ExecutionJobRead
from app.platform.runs.schemas import RunRead, RunStepRead


class FakeAgentTaskService:
    async def get_task(self, task_id: str) -> AgentTaskRead:
        return AgentTaskRead(
            task_id=task_id,
            state=TaskState.COMPLETED,
            envelope=AgentTaskEnvelope(
                task_id=task_id,
                run_id=task_id,
                step_id="step-1",
                correlation_id="corr-1",
                user_prompt="Need approval status",
                normalized_goal="Need approval status",
                task_class="answer_question",
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
                status="completed",
                started_at=None,
                completed_at="2026-04-10T00:02:00Z",
                failed_at=None,
                created_at="2026-04-10T00:00:00Z",
                updated_at="2026-04-10T00:02:00Z",
            ),
            step=RunStepRead(
                id="step-1",
                run_id=task_id,
                step_type="answer_question",
                title="answer question",
                status="completed",
                sequence_index=0,
                input_json={},
                output_json=None,
                approval_request_id="approval-1",
                tool_invocation_id=None,
                artifact_id=None,
                started_at=None,
                completed_at="2026-04-10T00:02:00Z",
                created_at="2026-04-10T00:00:00Z",
            ),
            job=ExecutionJobRead(
                id=task_id,
                target_id="mbp-primary",
                tool_name="agent.run_task",
                status="completed",
                payload_json={"task": {"task_id": task_id}},
                result_json=None,
                error_json=None,
                claimed_by="worker",
                created_at="2026-04-10T00:00:00Z",
                claimed_at="2026-04-10T00:00:05Z",
                completed_at="2026-04-10T00:02:00Z",
            ),
            events=[
                EventRead(
                    id="event-1",
                    run_id=task_id,
                    run_step_id="step-1",
                    entity_type="agent_task",
                    entity_id=task_id,
                    event_type="agent.task.created",
                    payload_json={"state": "queued"},
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


def build_client() -> TestClient:
    app = FastAPI()
    service = FakeAgentTaskService()
    app.include_router(router, prefix=settings.api_prefix)
    app.dependency_overrides[get_agent_task_service] = lambda: service
    return TestClient(app)


def test_stream_agent_task_includes_approval_events():
    client = build_client()

    with client.stream("GET", "/api/agent-tasks/task-1/stream") as response:
        body = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text()
        )

    assert response.status_code == 200
    assert "event: approval\n" in body
    assert '"approval_id": "approval-1"' in body
    assert "event: approval_decision\n" in body
    assert '"decision_id": "decision-1"' in body
    assert "event: terminal\n" in body
