import asyncio

from app.platform.agent_tasks.runtime import (
    OpenCodeRuntime,
    classify_task,
    default_allowed_backends_for_task,
    default_preferred_backend_for_task,
)
from app.platform.agent_tasks.schemas import (
    AgentTaskEnvelope,
    BackendName,
    ExecutionMode,
    TaskArtifact,
    TaskClass,
    TaskState,
    WorkerDispatchDecision,
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
    assert default_preferred_backend_for_task(TaskClass.CLASSIFY_ONLY) == BackendName.LOCAL_LLM
    assert default_preferred_backend_for_task(TaskClass.IMPLEMENT) == BackendName.CODEX


def test_opencode_runtime_executes_local_llm_task():
    runtime = OpenCodeRuntime.from_settings()
    reporter = RecordingReporter()

    result = asyncio.run(runtime.execute(build_envelope(), reporter))

    assert result.state == TaskState.COMPLETED
    assert result.backend == BackendName.LOCAL_LLM
    assert reporter.events[0][0] == "agent.task.routing.resolved"


def test_opencode_runtime_dry_run_executes_coding_backend_through_opencode():
    runtime = OpenCodeRuntime.from_settings()
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
