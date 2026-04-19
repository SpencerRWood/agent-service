import asyncio
from datetime import UTC, datetime

from fastapi import HTTPException, status

import app.platform.agent_tasks.service as agent_task_service_module
from app.platform.agent_tasks.schemas import (
    AgentTaskCreateRequest,
    AgentTaskEnvelope,
    AgentTaskResult,
    BackendName,
    ExecutionMode,
    TaskClass,
    TaskState,
    WorkerDispatchDecision,
)
from app.platform.agent_tasks.service import AgentTaskService
from app.platform.agents.service import AgentRegistry, RuntimeRegistry
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
        self.recent_runs: list[RunRead] = []

    async def create_run(self, request):
        run, _created = await self.create_or_get_run(request)
        return run

    async def create_or_get_run(self, request):
        self.create_run_calls += 1
        if request.idempotency_key:
            for run in self.runs.values():
                if run.idempotency_key == request.idempotency_key:
                    return run, False
        run_id = f"task-{self.create_run_calls}"
        run = _build_run_read(
            run_id,
            status="queued",
            idempotency_key=request.idempotency_key,
        )
        self.runs[run_id] = run
        return run, True

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

    async def get_run_by_idempotency_key(self, idempotency_key):
        for run in self.runs.values():
            if run.idempotency_key == idempotency_key:
                return run
        return None

    async def list_steps(self, run_id):
        return self.steps_by_run[run_id]

    async def list_recent_steps(self, *, limit=50):
        return self.recent_steps[:limit]

    async def list_recent_runs(self, *, limit=50):
        return self.recent_runs[:limit]

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
        self.events_by_run: dict[str, list[EventRead]] = {}

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
        return self.events_by_run.get(run_id, [])


class FakeArtifactService:
    def __init__(self) -> None:
        self.artifacts_by_run: dict[str, list[ArtifactRead]] = {}

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
        return self.artifacts_by_run.get(run_id, [])


class FakeApprovalService:
    def __init__(self) -> None:
        self.approvals_by_run: dict[str, list[ApprovalRequestRead]] = {}
        self.decisions_by_run: dict[str, list[ApprovalDecisionRead]] = {}

    async def create_request(self, request):
        approval = ApprovalRequestRead(
            id="approval-created",
            run_id=request.run_id,
            run_step_id=request.run_step_id,
            target_type=request.target_type,
            target_id=request.target_id,
            status="pending",
            decision_type="yes_no",
            policy_key=request.policy_key,
            reason=request.reason,
            request_payload_json=request.requested_decision,
            expires_at=None,
            created_at="2026-04-10T00:00:00Z",
            updated_at="2026-04-10T00:00:00Z",
        )
        self.approvals_by_run.setdefault(request.run_id, []).append(approval)
        return approval

    async def list_for_run(self, run_id):
        return self.approvals_by_run.get(
            run_id,
            [
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
            ],
        )

    async def list_decisions_for_run(self, run_id):
        return self.decisions_by_run.get(
            run_id,
            [
                ApprovalDecisionRead(
                    id="decision-1",
                    approval_request_id="approval-1",
                    decision="approved",
                    decided_by="reviewer-b",
                    comment="looks good",
                    decision_payload_json={"source": "openwebui"},
                    created_at="2026-04-10T00:01:00Z",
                )
            ],
        )


class FakeExecutionTargetService:
    def __init__(self) -> None:
        self.jobs_by_id: dict[str, ExecutionJobRead] = {}

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
        job = self.jobs_by_id.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Execution job not found"
            )
        return job


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


def test_create_task_resolves_backend_from_hint():
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
                backend_hint="codex",
            )
        )
    )

    assert response.task.envelope.preferred_backend == BackendName.CODEX


def test_create_task_resolves_backend_from_hint_not_in_allowed():
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
                prompt="Refactor the auth module",
                repo="agent-service",
                backend_hint="codex",
                allowed_backends=[BackendName.LOCAL_LLM],
            )
        )
    )

    assert response.task.envelope.preferred_backend == BackendName.LOCAL_LLM


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


def test_create_inline_plan_task_preserves_deferred_state(monkeypatch):
    class DeferredRuntime:
        async def execute(self, envelope, reporter):
            del envelope, reporter
            return AgentTaskResult(
                state=TaskState.DEFERRED_UNTIL_RESET,
                backend=BackendName.LOCAL_LLM,
                execution_mode=ExecutionMode.OPENCODE,
                summary="No backend is currently available. Task deferred until reset.",
                reason_code="backend_unavailable",
                raw_output={},
                artifacts=[],
                metrics={"executor": "opencode"},
                completed_at=datetime.now(UTC),
            )

    monkeypatch.setattr(
        agent_task_service_module.OpenCodeRuntime,
        "from_settings",
        classmethod(lambda cls: DeferredRuntime()),
    )

    run_service = FakeRunService()
    approval_service = FakeApprovalService()
    approval_service.approvals_by_run = {"task-1": []}
    approval_service.decisions_by_run = {"task-1": []}

    service = AgentTaskService(
        run_service=run_service,
        event_service=FakeEventService(),
        approval_service=approval_service,
        artifact_service=FakeArtifactService(),
        execution_target_service=FakeExecutionTargetService(),
    )

    response = asyncio.run(
        service.create_task(
            AgentTaskCreateRequest(
                task_class=TaskClass.PLAN_ONLY,
                public_agent_id="planner",
                runtime_key="planner_runtime",
                prompt="Give me a test plan",
            )
        )
    )

    assert response.task.state == TaskState.DEFERRED_UNTIL_RESET
    assert response.task.result is not None
    assert (
        response.task.result.summary
        == "No backend is currently available. Task deferred until reset."
    )
    assert response.task.result.completed_at is not None
    assert run_service.runs["task-1"].status == TaskState.DEFERRED_UNTIL_RESET.value
    assert (
        run_service.steps_by_run["task-1"][0].output_json["result"]["state"]
        == TaskState.DEFERRED_UNTIL_RESET.value
    )


def test_list_public_tasks_hides_enrichment_runs_and_merges_metadata():
    run_service = FakeRunService()
    event_service = FakeEventService()
    approval_service = FakeApprovalService()
    artifact_service = FakeArtifactService()
    execution_target_service = FakeExecutionTargetService()

    main_task_id = "fe95a4c9-75a8-47e5-87b8-91f476cd585e"
    tags_task_id = "37347370-8447-42b4-a7c6-5664f5ab56bc"
    title_task_id = "bf7bf2c4-0222-4666-b816-e84dcfa815cc"
    followups_task_id = "745161a8-8c00-4d5c-aad0-ec95b8749c7e"

    run_service.runs = {
        main_task_id: _build_run_read(main_task_id, status="completed"),
        tags_task_id: _build_run_read(tags_task_id, status="completed"),
        title_task_id: _build_run_read(title_task_id, status="completed"),
        followups_task_id: _build_run_read(followups_task_id, status="completed"),
    }
    run_service.steps_by_run = {
        main_task_id: [
            _build_step_read(
                main_task_id,
                "step-main",
                step_type="plan_only",
                input_json={},
                output_json={
                    "task_envelope": _build_envelope(
                        task_id=main_task_id,
                        prompt="Show me a plan for implementing multi-stage agent workflow",
                    ).model_dump(mode="json")
                },
            )
        ],
        tags_task_id: [
            _build_step_read(
                tags_task_id,
                "step-tags",
                step_type="plan_only",
                input_json={},
                output_json={
                    "task_envelope": _build_envelope(
                        task_id=tags_task_id,
                        prompt=f"### Task: Generate 1-3 broad tags categorizing the main themes of the chat history. Task ID: `{main_task_id}`",
                    ).model_dump(mode="json")
                },
            )
        ],
        title_task_id: [
            _build_step_read(
                title_task_id,
                "step-title",
                step_type="plan_only",
                input_json={},
                output_json={
                    "task_envelope": _build_envelope(
                        task_id=title_task_id,
                        prompt=f"### Task: Generate a concise, 3-5 word title with an emoji summarizing the chat history. Task ID: `{main_task_id}`",
                    ).model_dump(mode="json")
                },
            )
        ],
        followups_task_id: [
            _build_step_read(
                followups_task_id,
                "step-followups",
                step_type="plan_only",
                input_json={},
                output_json={
                    "task_envelope": _build_envelope(
                        task_id=followups_task_id,
                        prompt=f"### Task: Suggest 3-5 relevant follow-up questions or prompts that the user might naturally ask next in this conversation as a **user**. Task ID: `{main_task_id}`",
                    ).model_dump(mode="json")
                },
            )
        ],
    }
    run_service.recent_runs = [
        run_service.runs[tags_task_id],
        run_service.runs[title_task_id],
        run_service.runs[followups_task_id],
        run_service.runs[main_task_id],
    ]
    execution_target_service.jobs_by_id = {
        main_task_id: _build_job_read(
            main_task_id,
            prompt="Show me a plan for implementing multi-stage agent workflow",
            summary="Main plan",
        ),
        tags_task_id: _build_job_read(
            tags_task_id,
            prompt=f"### Task: Generate 1-3 broad tags categorizing the main themes of the chat history. Task ID: `{main_task_id}`",
            summary='{"tags": ["Technology", "Software Engineering"]}',
        ),
        title_task_id: _build_job_read(
            title_task_id,
            prompt=f"### Task: Generate a concise, 3-5 word title with an emoji summarizing the chat history. Task ID: `{main_task_id}`",
            summary='{"title": "📋 Multi-Stage Agent Plan"}',
        ),
        followups_task_id: _build_job_read(
            followups_task_id,
            prompt=f"### Task: Suggest 3-5 relevant follow-up questions or prompts that the user might naturally ask next in this conversation as a **user**. Task ID: `{main_task_id}`",
            summary='{"follow_ups": ["How do we handle retries?", "What tests should we add?"]}',
        ),
    }
    event_service.events_by_run = {
        main_task_id: [
            EventRead(
                id="event-main",
                run_id=main_task_id,
                run_step_id="step-main",
                entity_type="agent_task",
                entity_id=main_task_id,
                event_type="agent.task.completed",
                payload_json={"message": "Main plan completed."},
                actor_type="worker",
                actor_id="worker-b",
                trace_id="corr-main",
                created_at="2026-04-10T00:00:10Z",
            )
        ]
    }

    service = AgentTaskService(
        run_service=run_service,
        event_service=event_service,
        approval_service=approval_service,
        artifact_service=artifact_service,
        execution_target_service=execution_target_service,
    )

    response = asyncio.run(service.list_public_tasks(limit=10))

    assert len(response.items) == 1
    assert response.items[0].task_id == main_task_id
    assert response.items[0].conversation_title == "📋 Multi-Stage Agent Plan"
    assert response.items[0].conversation_tags == ["Technology", "Software Engineering"]
    assert response.items[0].follow_ups == [
        "How do we handle retries?",
        "What tests should we add?",
    ]


def test_handle_completed_job_spawns_handoff_task_from_workflow():
    run_service = FakeRunService()
    event_service = FakeEventService()
    approval_service = FakeApprovalService()
    approval_service.approvals_by_run = {"task-review": [], "task-1": []}
    approval_service.decisions_by_run = {"task-review": [], "task-1": []}
    artifact_service = FakeArtifactService()
    execution_target_service = FakeExecutionTargetService()

    reviewer_envelope = AgentTaskEnvelope(
        task_id="task-review",
        run_id="task-review",
        step_id="step-review",
        correlation_id="corr-review",
        user_prompt="Review the queue health check implementation.",
        normalized_goal="Review the queue health check implementation.",
        task_class=TaskClass.REVIEW,
        public_agent_id="reviewer",
        runtime_key="review_runtime",
        agent_system_prompt="Review carefully.",
        agent_workflow={
            "max_iterations": 1,
            "entry_step": "review",
            "steps": [
                {
                    "id": "review",
                    "instructions": "Review the implementation and hand back fixes if needed.",
                    "on_success": {"action": "finish"},
                    "on_failure": {
                        "action": "handoff",
                        "to": "coder",
                        "prompt": "Summarize the fixes for the coder.",
                    },
                }
            ],
        },
        target_repo="agent-service",
        target_branch="feature/review",
        allowed_backends=[BackendName.CODEX],
        preferred_backend=BackendName.CODEX,
        approval_policy={"mode": "required"},
        timeout_policy={"seconds": 900},
        return_artifacts=["summary"],
        metadata={"project_path": "/tmp/repo"},
        dispatch=WorkerDispatchDecision(
            target_id="worker-b",
            route_profile="implementation",
            reason="test",
        ),
    )
    run_service.runs = {"task-review": _build_run_read("task-review", status="completed")}
    run_service.steps_by_run = {
        "task-review": [
            _build_step_read(
                "task-review",
                "step-review",
                step_type="review",
                input_json={},
                output_json={"task_envelope": reviewer_envelope.model_dump(mode="json")},
            )
        ]
    }
    execution_target_service.jobs_by_id = {
        "task-review": ExecutionJobRead(
            id="task-review",
            target_id="worker-b",
            tool_name="agent.run_task",
            status="completed",
            payload_json={"task": reviewer_envelope.model_dump(mode="json")},
            result_json={
                "state": "completed",
                "backend": "codex",
                "execution_mode": "opencode",
                "summary": "Review completed with concrete follow-up guidance.",
                "workflow_outcome": "needs_changes",
                "reason_code": None,
                "raw_output": {},
                "artifacts": [],
                "metrics": {},
                "completed_at": datetime.now(UTC).isoformat(),
            },
            error_json=None,
            claimed_by="worker-b",
            created_at="2026-04-10T00:00:00Z",
            claimed_at="2026-04-10T00:00:01Z",
            completed_at="2026-04-10T00:00:02Z",
        )
    }

    runtime_registry = RuntimeRegistry()
    service = AgentTaskService(
        run_service=run_service,
        event_service=event_service,
        approval_service=approval_service,
        artifact_service=artifact_service,
        execution_target_service=execution_target_service,
        agent_registry=AgentRegistry(runtime_registry),
        runtime_registry=runtime_registry,
    )

    spawned = asyncio.run(
        service.handle_completed_job(
            task_id="task-review",
            result_payload=execution_target_service.jobs_by_id["task-review"].result_json,
        )
    )

    assert spawned is not None
    assert spawned.task_id == "task-1"
    child_step = run_service.steps_by_run["task-1"][0]
    assert child_step.input_json["public_agent_id"] == "coder"
    assert child_step.input_json["runtime_key"] == "coding_runtime"
    assert "Workflow handoff from reviewer to coder." in child_step.input_json["user_prompt"]
    assert (
        "Review completed with concrete follow-up guidance." in child_step.input_json["user_prompt"]
    )
    assert child_step.input_json["metadata"]["handoff_parent_task_id"] == "task-review"
    assert child_step.input_json["metadata"]["workflow_step_id"] == "implement-fixes"
    assert any(
        event.event_type == "agent.task.workflow.transitioned" for event in event_service.events
    )


def test_handle_completed_job_loops_coder_back_to_reviewer_on_success():
    run_service = FakeRunService()
    event_service = FakeEventService()
    approval_service = FakeApprovalService()
    approval_service.approvals_by_run = {"task-code": [], "task-1": []}
    approval_service.decisions_by_run = {"task-code": [], "task-1": []}
    artifact_service = FakeArtifactService()
    execution_target_service = FakeExecutionTargetService()

    coder_envelope = AgentTaskEnvelope(
        task_id="task-code",
        run_id="task-code",
        step_id="step-code",
        correlation_id="corr-code",
        user_prompt="Implement the reviewer fixes for queue health handling.",
        normalized_goal="Implement the reviewer fixes for queue health handling.",
        task_class=TaskClass.IMPLEMENT,
        public_agent_id="coder",
        runtime_key="coding_runtime",
        agent_system_prompt="Implement carefully.",
        agent_workflow={
            "max_iterations": 3,
            "entry_step": "implement-fixes",
            "steps": [
                {
                    "id": "implement-fixes",
                    "instructions": "Apply the requested remediation changes.",
                    "on_success": {
                        "action": "handoff",
                        "to": "reviewer",
                        "prompt": "Re-review the implementation.",
                    },
                    "on_failure": {"action": "finish"},
                }
            ],
        },
        target_repo="agent-service",
        target_branch="feature/review",
        allowed_backends=[BackendName.CODEX],
        preferred_backend=BackendName.CODEX,
        approval_policy={"mode": "none"},
        timeout_policy={"seconds": 900},
        return_artifacts=["summary"],
        metadata={"workflow_origin_task_id": "task-review", "workflow_iteration": 1},
        dispatch=WorkerDispatchDecision(
            target_id="worker-b",
            route_profile="implementation",
            reason="test",
        ),
    )
    run_service.runs = {"task-code": _build_run_read("task-code", status="completed")}
    run_service.steps_by_run = {
        "task-code": [
            _build_step_read(
                "task-code",
                "step-code",
                step_type="implement",
                input_json={},
                output_json={"task_envelope": coder_envelope.model_dump(mode="json")},
            )
        ]
    }
    execution_target_service.jobs_by_id = {
        "task-code": ExecutionJobRead(
            id="task-code",
            target_id="worker-b",
            tool_name="agent.run_task",
            status="completed",
            payload_json={"task": coder_envelope.model_dump(mode="json")},
            result_json={
                "state": "completed",
                "backend": "codex",
                "execution_mode": "opencode",
                "summary": "Implementation finished.",
                "workflow_outcome": "success",
                "reason_code": None,
                "raw_output": {},
                "artifacts": [],
                "metrics": {},
                "completed_at": datetime.now(UTC).isoformat(),
            },
            error_json=None,
            claimed_by="worker-b",
            created_at="2026-04-10T00:00:00Z",
            claimed_at="2026-04-10T00:00:01Z",
            completed_at="2026-04-10T00:00:02Z",
        )
    }

    runtime_registry = RuntimeRegistry()
    service = AgentTaskService(
        run_service=run_service,
        event_service=event_service,
        approval_service=approval_service,
        artifact_service=artifact_service,
        execution_target_service=execution_target_service,
        agent_registry=AgentRegistry(runtime_registry),
        runtime_registry=runtime_registry,
    )

    spawned = asyncio.run(
        service.handle_completed_job(
            task_id="task-code",
            result_payload=execution_target_service.jobs_by_id["task-code"].result_json,
        )
    )

    assert spawned is not None
    child_step = run_service.steps_by_run["task-1"][0]
    assert child_step.input_json["public_agent_id"] == "reviewer"
    assert child_step.input_json["metadata"]["workflow_iteration"] == 2
    assert child_step.input_json["metadata"]["workflow_origin_task_id"] == "task-review"


def _build_run_read(run_id: str, *, status: str, idempotency_key: str | None = None) -> RunRead:
    now = datetime.now(UTC).isoformat()
    return RunRead(
        id=run_id,
        idempotency_key=idempotency_key,
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


def _build_envelope(*, task_id: str, prompt: str) -> AgentTaskEnvelope:
    return AgentTaskEnvelope(
        task_id=task_id,
        run_id=task_id,
        step_id=f"step-{task_id}",
        correlation_id=f"corr-{task_id}",
        user_prompt=prompt,
        normalized_goal=prompt,
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
        metadata={},
        dispatch=WorkerDispatchDecision(
            target_id="worker-b",
            route_profile="cheap",
            reason="test",
        ),
    )


def _build_job_read(task_id: str, *, prompt: str, summary: str) -> ExecutionJobRead:
    now = datetime.now(UTC).isoformat()
    return ExecutionJobRead(
        id=task_id,
        target_id="worker-b",
        tool_name="agent.run_task",
        status="completed",
        payload_json={
            "task": _build_envelope(task_id=task_id, prompt=prompt).model_dump(mode="json")
        },
        result_json={
            "state": "completed",
            "backend": "local_llm",
            "execution_mode": "opencode",
            "summary": summary,
            "reason_code": None,
            "raw_output": {},
            "artifacts": [],
            "metrics": {},
            "completed_at": now,
        },
        error_json=None,
        claimed_by="worker-b",
        created_at=now,
        claimed_at=now,
        completed_at=now,
    )
