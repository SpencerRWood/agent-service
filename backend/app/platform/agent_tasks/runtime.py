from __future__ import annotations

import json
import shlex
from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from app.core.settings import settings
from app.integrations.providers.runner import CommandRunner, SubprocessCommandRunner
from app.platform.agent_tasks.contracts import ExecutorWorkPackage, ProjectContext
from app.platform.agent_tasks.schemas import (
    AgentTaskEnvelope,
    AgentTaskResult,
    BackendName,
    ExecutionPath,
    TaskArtifact,
    TaskClass,
)


class TaskProgressReporter(Protocol):
    async def publish(self, event_type: str, message: str, payload: dict | None = None) -> None: ...

    async def publish_artifact(self, artifact: TaskArtifact) -> None: ...


class TaskExecutor(Protocol):
    async def execute(
        self,
        envelope: AgentTaskEnvelope,
        reporter: TaskProgressReporter,
    ) -> AgentTaskResult: ...


class OpenCodeRoutingError(RuntimeError):
    """Raised when OpenCode cannot route a task cleanly."""


class OpenCodeExecutor:
    def __init__(
        self,
        *,
        command: str | None = None,
        dry_run: bool | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self._command = command or settings.opencode_command
        self._dry_run = settings.opencode_dry_run if dry_run is None else dry_run
        self._runner = runner or SubprocessCommandRunner()

    async def execute(
        self,
        envelope: AgentTaskEnvelope,
        reporter: TaskProgressReporter,
    ) -> AgentTaskResult:
        await reporter.publish(
            "agent.task.backend.started",
            f"Running OpenCode for {envelope.routing.selected_backend.value}.",
            {
                "backend": envelope.routing.selected_backend.value,
                "executor": "opencode",
            },
        )
        if self._dry_run:
            return self._build_dry_run_result(envelope)

        argv = shlex.split(self._command)
        if not argv:
            raise OpenCodeRoutingError("OpenCode command is not configured.")
        command_result = await self._runner.run(
            argv,
            stdin=self._build_work_package(envelope).model_dump_json(),
        )
        if command_result.exit_code != 0:
            raise OpenCodeRoutingError(
                "OpenCode command failed "
                f"(exit {command_result.exit_code}): "
                f"{command_result.stderr.strip() or command_result.stdout.strip()}"
            )
        try:
            payload = json.loads(command_result.stdout)
        except json.JSONDecodeError as exc:
            raise OpenCodeRoutingError("OpenCode command returned invalid JSON.") from exc
        return AgentTaskResult.model_validate(
            {
                "status": payload.get("status", "completed"),
                "backend": payload.get("backend", envelope.routing.selected_backend.value),
                "execution_path": envelope.routing.execution_path,
                "summary": payload.get("summary", "OpenCode task finished."),
                "raw_output": payload,
                "artifacts": payload.get("artifacts", []),
                "metrics": payload.get("metrics", {}),
                "completed_at": payload.get("completed_at"),
            }
        )

    def _build_dry_run_result(self, envelope: AgentTaskEnvelope) -> AgentTaskResult:
        summary = (
            f"OpenCode routed {envelope.task_class.value} to "
            f"{envelope.routing.selected_backend.value} in dry-run mode for "
            f"{envelope.repo or 'default'}."
        )
        artifact_type = (
            "summary"
            if envelope.routing.selected_backend == BackendName.LOCAL_LLM
            else "execution_result"
        )
        content = (
            {
                "markdown": (
                    f"# {envelope.task_class.value}\n\n{summary}\n\nPrompt:\n{envelope.prompt}"
                )
            }
            if envelope.routing.selected_backend == BackendName.LOCAL_LLM
            else {
                "provider": envelope.routing.selected_backend.value,
                "branch_name": f"agent-task/{envelope.task_id}",
                "commit_shas": [envelope.task_id[:12]],
                "pr_title": f"[{envelope.routing.selected_backend.value}] {envelope.prompt[:64]}",
                "pr_body": (
                    "Opened by agent service via OpenCode.\n\n"
                    f"Run: {envelope.run_id}\n"
                    f"Repo: {envelope.repo or 'default'}\n"
                    f"Backend: {envelope.routing.selected_backend.value}"
                ),
                "pr_url": f"https://{settings.git_provider_name}.local/{envelope.repo or 'default'}/pull/{envelope.task_id[:8]}",
                "pr_number": int(sha256(envelope.task_id.encode("utf-8")).hexdigest()[:6], 16),
                "execution_summary": summary,
                "known_risks": ["Dry-run OpenCode executor did not invoke a real backend session."],
            }
        )
        return AgentTaskResult(
            status="completed",
            backend=envelope.routing.selected_backend,
            execution_path=envelope.routing.execution_path,
            summary=summary,
            raw_output={
                "mode": "dry_run",
                "command": self._command,
                "task_class": envelope.task_class.value,
                "backend": envelope.routing.selected_backend.value,
                "fallback_backend": (
                    envelope.routing.fallback_backend.value
                    if envelope.routing.fallback_backend is not None
                    else None
                ),
            },
            artifacts=[
                TaskArtifact(
                    artifact_type=artifact_type,
                    title="Task Result",
                    content=content,
                    provenance={
                        "backend": envelope.routing.selected_backend.value,
                        "executor": "opencode",
                    },
                    status="completed",
                )
            ],
            metrics={"mode": "dry_run"},
            completed_at=datetime.now(UTC),
        )

    def _build_work_package(self, envelope: AgentTaskEnvelope) -> ExecutorWorkPackage:
        return ExecutorWorkPackage(
            run_id=envelope.run_id,
            backend=self.backend_name.value,
            repo=envelope.repo or "default",
            project=ProjectContext(project_path=envelope.project_path),
            branch_strategy=f"agent-task/{envelope.task_id}",
            instructions=envelope.prompt,
            constraints=[
                f"task_class={envelope.task_class.value}",
                f"execution_path={envelope.routing.execution_path.value}",
            ],
            acceptance_criteria=_acceptance_criteria_for_task(envelope.task_class),
            source_metadata={
                "task_id": envelope.task_id,
                "trace_id": envelope.trace_id,
                "route_profile": envelope.routing.route_profile,
                "selected_backend": envelope.routing.selected_backend.value,
                "fallback_backend": (
                    envelope.routing.fallback_backend.value
                    if envelope.routing.fallback_backend is not None
                    else None
                ),
                "execution_target": envelope.routing.target_id,
                "context": envelope.context,
                "approvals": envelope.approvals,
                "branch_workflow": envelope.branch_workflow,
                "usage_limits": envelope.usage_limits,
            },
        )


class OpenCodeRuntime:
    def __init__(self, executor: TaskExecutor) -> None:
        self._executor = executor

    @classmethod
    def from_settings(
        cls,
        *,
        opencode_command: str | None = None,
    ) -> OpenCodeRuntime:
        runner = SubprocessCommandRunner()
        return cls(executor=OpenCodeExecutor(command=opencode_command, runner=runner))

    async def execute(
        self,
        envelope: AgentTaskEnvelope,
        reporter: TaskProgressReporter,
    ) -> AgentTaskResult:
        await reporter.publish(
            "agent.task.routing.resolved",
            (
                f"{envelope.routing.execution_path.value} path selected "
                f"{envelope.routing.selected_backend.value} via opencode."
            ),
            {
                "execution_path": envelope.routing.execution_path.value,
                "backend": envelope.routing.selected_backend.value,
                "fallback_backend": (
                    envelope.routing.fallback_backend.value
                    if envelope.routing.fallback_backend is not None
                    else None
                ),
                "executor": "opencode",
            },
        )
        try:
            return await self._executor.execute(envelope, reporter)
        except Exception as primary_exc:
            if (
                envelope.routing.fallback_backend is None
                or envelope.routing.execution_path != ExecutionPath.OPENCODE
            ):
                raise
            await reporter.publish(
                "agent.task.backend.fallback",
                (
                    f"{envelope.routing.selected_backend.value} failed inside opencode. "
                    f"Retrying with {envelope.routing.fallback_backend.value}."
                ),
                {"error": str(primary_exc)},
            )
            fallback_envelope = envelope.model_copy(
                update={
                    "routing": envelope.routing.model_copy(
                        update={
                            "selected_backend": envelope.routing.fallback_backend,
                            "fallback_backend": None,
                        }
                    )
                }
            )
            result = await self._executor.execute(fallback_envelope, reporter)
            result.raw_output = {
                "primary_error": str(primary_exc),
                **result.raw_output,
            }
            return result


def default_backend_for_task(task_class: TaskClass) -> BackendName:
    if task_class in {
        TaskClass.CLASSIFY_ONLY,
        TaskClass.PLAN_ONLY,
        TaskClass.SUMMARIZE,
    }:
        return BackendName.LOCAL_LLM
    return BackendName.CODEX


def default_fallback_for_task(task_class: TaskClass) -> BackendName | None:
    if default_backend_for_task(task_class) == BackendName.CODEX:
        return BackendName.COPILOT_CLI
    return None


def available_route_profiles(task_class: TaskClass) -> Sequence[str]:
    if task_class in {TaskClass.CLASSIFY_ONLY, TaskClass.PLAN_ONLY, TaskClass.SUMMARIZE}:
        return ("cheap", "local")
    return ("implementation", "coding")


def _acceptance_criteria_for_task(task_class: TaskClass) -> list[str]:
    if task_class == TaskClass.IMPLEMENT:
        return ["Requested implementation is completed and summarized."]
    if task_class == TaskClass.DEBUG:
        return ["Root cause is identified and a fix is proposed or applied."]
    if task_class == TaskClass.REVIEW:
        return ["Review findings are explicit and ordered by severity."]
    if task_class == TaskClass.INSPECT_REPO:
        return ["Repository structure and constraints are summarized."]
    return ["Task output is returned in a concise final artifact."]
