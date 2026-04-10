import asyncio

from app.platform.agent_tasks.runtime import (
    OpenCodeRuntime,
    default_backend_for_task,
    default_fallback_for_task,
)
from app.platform.agent_tasks.schemas import (
    AgentTaskEnvelope,
    AgentTaskRoutingDecision,
    BackendName,
    ExecutionPath,
    TaskArtifact,
    TaskClass,
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
    backend: BackendName = BackendName.LOCAL_LLM,
    fallback_backend: BackendName | None = None,
    execution_path: ExecutionPath = ExecutionPath.OPENCODE,
) -> AgentTaskEnvelope:
    return AgentTaskEnvelope(
        task_id="task-1",
        run_id="task-1",
        step_id="step-1",
        trace_id="trace-1",
        task_class=task_class,
        prompt="Inspect the routing plan",
        repo="agent-service",
        routing=AgentTaskRoutingDecision(
            execution_path=execution_path,
            selected_backend=backend,
            fallback_backend=fallback_backend,
            target_id="worker-b",
            route_profile="cheap",
            reason="test",
        ),
    )


def test_default_routing_policy_matches_requested_defaults():
    assert default_backend_for_task(TaskClass.CLASSIFY_ONLY) == BackendName.LOCAL_LLM
    assert default_backend_for_task(TaskClass.IMPLEMENT) == BackendName.CODEX
    assert default_fallback_for_task(TaskClass.IMPLEMENT) == BackendName.COPILOT_CLI
    assert default_fallback_for_task(TaskClass.SUMMARIZE) is None


def test_opencode_runtime_executes_local_llm_task():
    runtime = OpenCodeRuntime.from_settings()
    reporter = RecordingReporter()

    result = asyncio.run(runtime.execute(build_envelope(), reporter))

    assert result.status == "completed"
    assert result.backend == BackendName.LOCAL_LLM
    assert reporter.events[0][0] == "agent.task.routing.resolved"


def test_opencode_runtime_dry_run_executes_coding_backend_through_opencode():
    runtime = OpenCodeRuntime.from_settings()
    reporter = RecordingReporter()

    result = asyncio.run(
        runtime.execute(
            build_envelope(
                task_class=TaskClass.IMPLEMENT,
                backend=BackendName.CODEX,
                fallback_backend=BackendName.COPILOT_CLI,
            ),
            reporter,
        )
    )

    assert result.status == "completed"
    assert result.backend == BackendName.CODEX
    assert result.raw_output["backend"] == "codex"
