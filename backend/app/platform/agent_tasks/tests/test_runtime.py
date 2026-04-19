import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.platform.agent_tasks.runtime import (
    OpenCodeExecutor,
    OpenCodeRuntime,
    classify_task,
    default_allowed_backends_for_task,
    default_preferred_backend_for_task,
)
from app.platform.agent_tasks.schemas import (
    AgentTaskEnvelope,
    BackendName,
    ExecutionMode,
    ReasonCode,
    TaskArtifact,
    TaskClass,
    TaskState,
    WorkerDispatchDecision,
    WorkflowOutcome,
)


class RecordingReporter:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.artifacts: list[TaskArtifact] = []

    async def publish(self, event_type: str, message: str, payload: dict | None = None) -> None:
        del payload
        self.events.append((event_type, message))

    async def publish_artifact(self, artifact: TaskArtifact) -> None:
        self.artifacts.append(artifact)


def build_envelope(
    *,
    task_class: TaskClass = TaskClass.PLAN_ONLY,
    preferred_backend: BackendName = BackendName.LOCAL_LLM,
    allowed_backends: list[BackendName] | None = None,
) -> AgentTaskEnvelope:
    return AgentTaskEnvelope(
        task_id="task-1",
        run_id="task-1",
        step_id="step-1",
        correlation_id="corr-1",
        user_prompt="Inspect the routing plan",
        normalized_goal="Inspect the routing plan",
        task_class=task_class,
        target_repo="agent-service",
        target_branch=None,
        execution_mode=ExecutionMode.OPENCODE,
        allowed_backends=allowed_backends or default_allowed_backends_for_task(task_class),
        preferred_backend=preferred_backend,
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


def test_task_classification_defaults_match_required_guidance():
    assert classify_task("please summarize this repo") == TaskClass.SUMMARIZE
    assert classify_task("what API path streams task progress?") == TaskClass.ANSWER_QUESTION
    assert classify_task("analyze the tradeoffs between these two approaches") == TaskClass.ANALYZE
    assert classify_task("refactor this module for readability") == TaskClass.REFACTOR
    assert classify_task("write tests for the execution target router") == TaskClass.TEST
    assert classify_task("update the README with setup instructions") == TaskClass.DOCUMENT
    assert default_preferred_backend_for_task(TaskClass.CLASSIFY_ONLY) == BackendName.LOCAL_LLM
    assert default_preferred_backend_for_task(TaskClass.ANSWER_QUESTION) == BackendName.LOCAL_LLM
    assert default_preferred_backend_for_task(TaskClass.ANALYZE) == BackendName.LOCAL_LLM
    assert default_preferred_backend_for_task(TaskClass.IMPLEMENT) == BackendName.CODEX
    assert default_preferred_backend_for_task(TaskClass.REFACTOR) == BackendName.CODEX
    assert default_preferred_backend_for_task(TaskClass.TEST) == BackendName.CODEX
    assert default_preferred_backend_for_task(TaskClass.DOCUMENT) == BackendName.CODEX


def test_opencode_runtime_executes_local_llm_task():
    runtime = OpenCodeRuntime(executor=OpenCodeExecutor(dry_run=True))
    reporter = RecordingReporter()

    result = asyncio.run(runtime.execute(build_envelope(), reporter))

    assert result.state == TaskState.COMPLETED
    assert result.backend == BackendName.LOCAL_LLM
    assert result.workflow_outcome == WorkflowOutcome.SUCCESS
    assert reporter.events[0][0] == "agent.task.routing.resolved"


def test_opencode_runtime_dry_run_executes_coding_backend_through_opencode():
    runtime = OpenCodeRuntime(executor=OpenCodeExecutor(dry_run=True))
    reporter = RecordingReporter()

    result = asyncio.run(
        runtime.execute(
            build_envelope(
                task_class=TaskClass.IMPLEMENT,
                preferred_backend=BackendName.CODEX,
            ),
            reporter,
        )
    )

    assert result.state == TaskState.COMPLETED
    assert result.backend == BackendName.CODEX
    assert result.raw_output["backend"] == "codex"
    assert result.workflow_outcome == WorkflowOutcome.SUCCESS


def test_opencode_runtime_honors_explicit_codex_for_inspect_repo():
    runtime = OpenCodeRuntime(executor=OpenCodeExecutor(dry_run=True))
    reporter = RecordingReporter()

    result = asyncio.run(
        runtime.execute(
            build_envelope(
                task_class=TaskClass.INSPECT_REPO,
                preferred_backend=BackendName.CODEX,
                allowed_backends=[BackendName.CODEX, BackendName.LOCAL_LLM],
            ),
            reporter,
        )
    )

    assert result.state == TaskState.COMPLETED
    assert result.backend == BackendName.CODEX
    assert result.raw_output["backend"] == "codex"
    assert result.workflow_outcome == WorkflowOutcome.SUCCESS


def test_opencode_runtime_requests_approval_for_available_coding_fallback(monkeypatch):
    runtime = OpenCodeRuntime(executor=OpenCodeExecutor(dry_run=False))
    reporter = RecordingReporter()

    async def fake_preflight(*, backend, task_id, task_class, repo):
        del task_id, task_class, repo
        available = backend in {BackendName.CODEX, BackendName.COPILOT_CLI}
        return SimpleNamespace(
            available=available,
            reason_code=(
                ReasonCode.CODEX_AVAILABLE
                if backend == BackendName.CODEX and available
                else ReasonCode.COPILOT_AVAILABLE
                if backend == BackendName.COPILOT_CLI and available
                else ReasonCode.BACKEND_UNAVAILABLE
            ),
            retry_after=datetime.now(UTC) + timedelta(minutes=15),
        )

    async def fake_execute(*, work_package, backend):
        del work_package, backend
        raise AssertionError("execute should not run before fallback approval")

    monkeypatch.setattr(runtime._executor._adapter, "preflight", fake_preflight)
    monkeypatch.setattr(runtime._executor._adapter, "execute", fake_execute)

    result = asyncio.run(runtime.execute(build_envelope(), reporter))

    assert result.state == TaskState.PENDING_APPROVAL
    assert result.backend == BackendName.CODEX
    assert result.raw_output["suggested_backend"] == "codex"
    assert result.raw_output["available_backends"] == ["codex", "copilot_cli"]
