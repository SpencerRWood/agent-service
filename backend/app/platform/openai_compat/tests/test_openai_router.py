from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.settings import settings
from app.platform.agent_tasks.schemas import (
    AgentTaskCreateResponse,
    AgentTaskEnvelope,
    AgentTaskRead,
    AgentTaskResult,
    BackendName,
    ExecutionMode,
    TaskArtifact,
    TaskState,
    WorkerDispatchDecision,
)
from app.platform.agent_tasks.task_store import TaskStore, to_public_task
from app.platform.agents.service import AgentRegistry, RuntimeRegistry
from app.platform.approvals.schemas import ApprovalRequestRead
from app.platform.events.schemas import EventRead
from app.platform.execution_targets.schemas import ExecutionJobRead
from app.platform.openai_compat.router import get_openai_compat_service, router
from app.platform.openai_compat.service import OpenAICompatService
from app.platform.runs.schemas import RunRead, RunStepRead


class FakeTaskStore(TaskStore):
    def __init__(self) -> None:
        self.created_requests = []
        self.tasks: dict[str, AgentTaskRead] = {}

    async def create_task(self, request):
        self.created_requests.append(request)
        task_id = f"task-{len(self.created_requests)}"
        approval_required = str(request.approval_policy.get("mode")) == "required"
        state = TaskState.PENDING_APPROVAL if approval_required else TaskState.COMPLETED
        job = (
            None
            if approval_required
            else ExecutionJobRead(
                id=task_id,
                target_id="worker-b",
                tool_name="agent.run_task",
                status="completed",
                payload_json={"task": {"task_id": task_id}},
                result_json={},
                error_json=None,
                claimed_by="worker-b",
                created_at="2026-04-10T00:00:00Z",
                claimed_at="2026-04-10T00:00:01Z",
                completed_at="2026-04-10T00:00:02Z",
            )
        )
        result = (
            None
            if approval_required
            else AgentTaskResult(
                state=TaskState.COMPLETED,
                backend=BackendName.CODEX,
                execution_mode=ExecutionMode.OPENCODE,
                summary=f"Completed for {request.public_agent_id}",
                artifacts=[
                    TaskArtifact(
                        artifact_type="execution_result",
                        title="Task Result",
                        content={"markdown": "done"},
                        provenance={},
                    )
                ],
            )
        )
        approvals = (
            [
                ApprovalRequestRead(
                    id="approval-1",
                    run_id=task_id,
                    run_step_id="step-1",
                    target_type="agent_task",
                    target_id=task_id,
                    status="pending",
                    decision_type="yes_no",
                    policy_key="agent_task_execution",
                    reason="Approve",
                    request_payload_json={},
                    expires_at=None,
                    created_at="2026-04-10T00:00:00Z",
                    updated_at="2026-04-10T00:00:00Z",
                )
            ]
            if approval_required
            else []
        )
        task = AgentTaskRead(
            task_id=task_id,
            state=state,
            envelope=AgentTaskEnvelope(
                task_id=task_id,
                run_id=task_id,
                step_id="step-1",
                correlation_id="corr-1",
                user_prompt=request.prompt,
                normalized_goal=request.prompt,
                task_class=request.task_class,
                public_agent_id=request.public_agent_id,
                runtime_key=request.runtime_key,
                agent_system_prompt=request.agent_system_prompt,
                agent_workflow=request.agent_workflow,
                target_repo=request.repo,
                target_branch=request.target_branch,
                execution_mode=request.execution_mode,
                allowed_backends=[BackendName.CODEX],
                preferred_backend=BackendName.CODEX,
                approval_policy=request.approval_policy,
                timeout_policy=request.timeout_policy or {"seconds": 900},
                return_artifacts=request.return_artifacts,
                metadata=request.metadata,
                dispatch=WorkerDispatchDecision(
                    target_id="worker-b",
                    route_profile=request.route_profile,
                    reason="test",
                ),
            ),
            run=RunRead(
                id=task_id,
                prompt_id=None,
                intent_id=None,
                status=state.value,
                started_at=None,
                completed_at="2026-04-10T00:00:02Z" if not approval_required else None,
                failed_at=None,
                created_at="2026-04-10T00:00:00Z",
                updated_at="2026-04-10T00:00:02Z",
            ),
            step=RunStepRead(
                id="step-1",
                run_id=task_id,
                step_type=request.task_class.value,
                title=request.task_class.value,
                status=state.value,
                sequence_index=0,
                input_json={},
                output_json=None,
                approval_request_id="approval-1" if approval_required else None,
                tool_invocation_id=None,
                artifact_id=None,
                started_at=None,
                completed_at="2026-04-10T00:00:02Z" if not approval_required else None,
                created_at="2026-04-10T00:00:00Z",
            ),
            job=job,
            events=[
                EventRead(
                    id="event-1",
                    run_id=task_id,
                    run_step_id="step-1",
                    entity_type="agent_task",
                    entity_id=task_id,
                    event_type="agent.task.created",
                    payload_json={"message": f"Created {request.public_agent_id} task."},
                    actor_type="broker",
                    actor_id="agent-services",
                    trace_id="corr-1",
                    created_at="2026-04-10T00:00:00Z",
                )
            ],
            approvals=approvals,
            approval_decisions=[],
            artifacts=[],
            result=result,
        )
        self.tasks[task_id] = task
        return AgentTaskCreateResponse(task=task)

    async def get_task(self, task_id: str) -> AgentTaskRead:
        return self.tasks[task_id]

    async def get_public_task(self, task_id: str):
        return to_public_task(self.tasks[task_id])


def build_client(task_store: FakeTaskStore) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix=settings.api_prefix)
    runtime_registry = RuntimeRegistry()
    service = OpenAICompatService(
        agent_registry=AgentRegistry(runtime_registry),
        runtime_registry=runtime_registry,
        task_store=task_store,
    )
    app.dependency_overrides[get_openai_compat_service] = lambda: service
    return TestClient(app)


def test_list_models_exposes_public_agent_ids():
    client = build_client(FakeTaskStore())

    response = client.get("/api/v1/models")

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]]
    assert ids == ["planner", "rag-analyst", "coder", "reviewer"]


def test_chat_completion_dispatches_selected_agent_id_to_task_runtime():
    task_store = FakeTaskStore()
    client = build_client(task_store)

    response = client.post(
        "/api/v1/chat/completions",
        json={
            "model": "coder",
            "messages": [{"role": "user", "content": "Implement a queue health check."}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert task_store.created_requests[0].public_agent_id == "coder"
    assert task_store.created_requests[0].runtime_key == "coding_runtime"
    assert task_store.created_requests[0].task_class.value == "implement"
    assert task_store.created_requests[0].agent_system_prompt
    assert task_store.created_requests[0].agent_workflow["entry_step"] == "implement-fixes"
    assert (
        task_store.created_requests[0].agent_workflow["steps"][0]["on_success"]["to"] == "reviewer"
    )
    assert task_store.created_requests[0].wait_for_completion is False
    assert task_store.created_requests[0].metadata["idempotency_scope"] == "content_window"
    assert task_store.created_requests[0].metadata["idempotency_window_seconds"] == 45
    assert task_store.created_requests[0].metadata["idempotency_key"]
    assert response.json()["task"]["state"] == "completed"


def test_unknown_model_returns_not_found():
    client = build_client(FakeTaskStore())

    response = client.post(
        "/api/v1/chat/completions",
        json={
            "model": "ghost-agent",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 404
    assert "Unknown agent" in response.json()["detail"]


def test_reviewer_agent_surfaces_pending_approval_state():
    task_store = FakeTaskStore()
    client = build_client(task_store)

    response = client.post(
        "/api/v1/chat/completions",
        json={
            "model": "reviewer",
            "messages": [{"role": "user", "content": "Review this change set."}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task"]["state"] == "pending_approval"
    assert payload["task"]["approve_url"] == "/api/agent-tasks/task-1/approve"
    assert task_store.created_requests[0].agent_workflow["entry_step"] == "review"
    assert task_store.created_requests[0].agent_workflow["steps"][0]["run"] == "pytest"
    assert (
        task_store.created_requests[0].agent_workflow["steps"][0]["on_needs_changes"]["to"]
        == "coder"
    )
    assert "requires approval" in payload["choices"][0]["message"]["content"]


def test_approval_behavior_comes_from_runtime_mapping_not_agent_id():
    task_store = FakeTaskStore()
    runtime_registry = RuntimeRegistry()
    runtime_registry._runtimes["coding_runtime"].approval_mode = "required"
    app = FastAPI()
    app.include_router(router, prefix=settings.api_prefix)
    service = OpenAICompatService(
        agent_registry=AgentRegistry(runtime_registry),
        runtime_registry=runtime_registry,
        task_store=task_store,
    )
    app.dependency_overrides[get_openai_compat_service] = lambda: service
    client = TestClient(app)

    response = client.post(
        "/api/v1/chat/completions",
        json={
            "model": "coder",
            "messages": [{"role": "user", "content": "Implement carefully."}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert task_store.created_requests[0].approval_policy["mode"] == "required"
    assert response.json()["task"]["state"] == "pending_approval"


def test_streaming_chat_completion_emits_task_metadata_and_done_marker():
    client = build_client(FakeTaskStore())

    with client.stream(
        "POST",
        "/api/v1/chat/completions",
        json={
            "model": "coder",
            "messages": [{"role": "user", "content": "Implement the endpoint."}],
            "stream": True,
        },
    ) as response:
        body = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text()
        )

    assert response.status_code == 200
    assert "chat.completion.chunk" in body
    assert '"id": "task-1"' in body
    assert "[DONE]" in body


def test_inline_completed_task_returns_summary_without_waiting_for_stream():
    class InlineCompletedTaskStore(FakeTaskStore):
        async def create_task(self, request):
            self.created_requests.append(request)
            task_id = "task-inline"
            task = AgentTaskRead(
                task_id=task_id,
                state=TaskState.COMPLETED,
                envelope=AgentTaskEnvelope(
                    task_id=task_id,
                    run_id=task_id,
                    step_id="step-1",
                    correlation_id="corr-1",
                    user_prompt=request.prompt,
                    normalized_goal=request.prompt,
                    task_class=request.task_class,
                    public_agent_id=request.public_agent_id,
                    runtime_key=request.runtime_key,
                    agent_system_prompt=request.agent_system_prompt,
                    agent_workflow=request.agent_workflow,
                    target_repo=request.repo,
                    target_branch=request.target_branch,
                    execution_mode=request.execution_mode,
                    allowed_backends=[BackendName.CODEX],
                    preferred_backend=BackendName.CODEX,
                    approval_policy=request.approval_policy,
                    timeout_policy=request.timeout_policy or {"seconds": 900},
                    return_artifacts=request.return_artifacts,
                    metadata=request.metadata,
                    dispatch=WorkerDispatchDecision(
                        target_id="worker-b",
                        route_profile=request.route_profile,
                        reason="test",
                    ),
                ),
                run=RunRead(
                    id=task_id,
                    prompt_id=None,
                    intent_id=None,
                    status="completed",
                    started_at=None,
                    completed_at="2026-04-10T00:00:02Z",
                    failed_at=None,
                    created_at="2026-04-10T00:00:00Z",
                    updated_at="2026-04-10T00:00:02Z",
                ),
                step=RunStepRead(
                    id="step-1",
                    run_id=task_id,
                    step_type=request.task_class.value,
                    title=request.task_class.value,
                    status="completed",
                    sequence_index=0,
                    input_json={},
                    output_json={
                        "result": {
                            "state": "completed",
                            "backend": "local_llm",
                            "execution_mode": "opencode",
                            "summary": "Planner produced the final answer inline.",
                            "artifacts": [],
                            "metrics": {},
                            "completed_at": "2026-04-10T00:00:02Z",
                        }
                    },
                    approval_request_id=None,
                    tool_invocation_id=None,
                    artifact_id=None,
                    started_at=None,
                    completed_at="2026-04-10T00:00:02Z",
                    created_at="2026-04-10T00:00:00Z",
                ),
                job=None,
                events=[],
                approvals=[],
                approval_decisions=[],
                artifacts=[],
                result=AgentTaskResult(
                    state=TaskState.COMPLETED,
                    backend=BackendName.LOCAL_LLM,
                    execution_mode=ExecutionMode.OPENCODE,
                    summary="Planner produced the final answer inline.",
                    artifacts=[],
                    metrics={},
                    completed_at="2026-04-10T00:00:02Z",
                ),
            )
            self.tasks[task_id] = task
            return AgentTaskCreateResponse(task=task)

    client = build_client(InlineCompletedTaskStore())

    response = client.post(
        "/api/v1/chat/completions",
        json={
            "model": "planner",
            "messages": [{"role": "user", "content": "Make a short plan."}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task"]["state"] == "completed"
    assert (
        payload["choices"][0]["message"]["content"] == "Planner produced the final answer inline."
    )


def test_inline_deferred_task_returns_summary_without_waiting_for_stream():
    class InlineDeferredTaskStore(FakeTaskStore):
        async def create_task(self, request):
            self.created_requests.append(request)
            task_id = "task-inline-deferred"
            task = AgentTaskRead(
                task_id=task_id,
                state=TaskState.DEFERRED_UNTIL_RESET,
                envelope=AgentTaskEnvelope(
                    task_id=task_id,
                    run_id=task_id,
                    step_id="step-1",
                    correlation_id="corr-1",
                    user_prompt=request.prompt,
                    normalized_goal=request.prompt,
                    task_class=request.task_class,
                    public_agent_id=request.public_agent_id,
                    runtime_key=request.runtime_key,
                    agent_system_prompt=request.agent_system_prompt,
                    agent_workflow=request.agent_workflow,
                    target_repo=request.repo,
                    target_branch=request.target_branch,
                    execution_mode=request.execution_mode,
                    allowed_backends=[BackendName.LOCAL_LLM],
                    preferred_backend=BackendName.LOCAL_LLM,
                    approval_policy=request.approval_policy,
                    timeout_policy=request.timeout_policy or {"seconds": 900},
                    return_artifacts=request.return_artifacts,
                    metadata=request.metadata,
                    dispatch=WorkerDispatchDecision(
                        target_id="worker-b",
                        route_profile=request.route_profile,
                        reason="test",
                    ),
                ),
                run=RunRead(
                    id=task_id,
                    prompt_id=None,
                    intent_id=None,
                    status="deferred_until_reset",
                    started_at=None,
                    completed_at="2026-04-10T00:00:02Z",
                    failed_at=None,
                    created_at="2026-04-10T00:00:00Z",
                    updated_at="2026-04-10T00:00:02Z",
                ),
                step=RunStepRead(
                    id="step-1",
                    run_id=task_id,
                    step_type=request.task_class.value,
                    title=request.task_class.value,
                    status="deferred_until_reset",
                    sequence_index=0,
                    input_json={},
                    output_json={
                        "result": {
                            "state": "deferred_until_reset",
                            "backend": "local_llm",
                            "execution_mode": "opencode",
                            "summary": "No backend is currently available. Task deferred until reset.",
                            "artifacts": [],
                            "metrics": {},
                            "completed_at": "2026-04-10T00:00:02Z",
                        }
                    },
                    approval_request_id=None,
                    tool_invocation_id=None,
                    artifact_id=None,
                    started_at=None,
                    completed_at="2026-04-10T00:00:02Z",
                    created_at="2026-04-10T00:00:00Z",
                ),
                job=None,
                events=[],
                approvals=[],
                approval_decisions=[],
                artifacts=[],
                result=AgentTaskResult(
                    state=TaskState.DEFERRED_UNTIL_RESET,
                    backend=BackendName.LOCAL_LLM,
                    execution_mode=ExecutionMode.OPENCODE,
                    summary="No backend is currently available. Task deferred until reset.",
                    artifacts=[],
                    metrics={},
                    completed_at="2026-04-10T00:00:02Z",
                ),
            )
            self.tasks[task_id] = task
            return AgentTaskCreateResponse(task=task)

    client = build_client(InlineDeferredTaskStore())

    response = client.post(
        "/api/v1/chat/completions",
        json={
            "model": "planner",
            "messages": [{"role": "user", "content": "Give me a test plan."}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task"]["state"] == "deferred_until_reset"
    assert (
        payload["choices"][0]["message"]["content"]
        == "No backend is currently available. Task deferred until reset."
    )


def test_streaming_enrichment_task_suppresses_progress_messages():
    client = build_client(FakeTaskStore())

    with client.stream(
        "POST",
        "/api/v1/chat/completions",
        json={
            "model": "planner",
            "messages": [
                {
                    "role": "user",
                    "content": "### Task: Generate 1-3 broad tags categorizing the main themes of the chat history.",
                }
            ],
            "stream": True,
        },
    ) as response:
        body = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text()
        )

    assert response.status_code == 200
    assert "Created planner task." not in body
    assert "Completed for planner" in body
    assert "[DONE]" in body


def test_chat_completion_prefers_request_identifiers_for_idempotency():
    task_store = FakeTaskStore()
    client = build_client(task_store)

    response = client.post(
        "/api/v1/chat/completions",
        json={
            "model": "planner",
            "messages": [{"role": "user", "content": "Plan the rollout."}],
            "metadata": {
                "conversation_id": "conv-123",
                "message_id": "msg-456",
            },
        },
    )

    assert response.status_code == 200
    assert task_store.created_requests[0].metadata["idempotency_scope"] == "request_identifiers"
    assert task_store.created_requests[0].metadata["idempotency_window_seconds"] == 900
