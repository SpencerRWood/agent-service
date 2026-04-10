from __future__ import annotations

import json
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Protocol

from app.core.settings import settings
from app.integrations.providers.runner import CommandRunner, SubprocessCommandRunner
from app.platform.agent_tasks.contracts import ExecutorWorkPackage, ProjectContext
from app.platform.agent_tasks.schemas import (
    AgentTaskEnvelope,
    AgentTaskResult,
    BackendName,
    ExecutionMode,
    ReasonCode,
    TaskArtifact,
    TaskClass,
    TaskState,
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


@dataclass(slots=True)
class BackendSelection:
    backend: BackendName
    reason_codes: list[ReasonCode]
    rerouted_from: BackendName | None = None


@dataclass(slots=True)
class PreflightStatus:
    backend: BackendName
    available: bool
    reason_code: ReasonCode
    retry_after: datetime | None = None


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
        selection = self._select_backend(envelope)
        await _publish_state(
            reporter,
            state=TaskState.PREFLIGHT_CHECK,
            message="Running backend availability checks.",
            payload={
                "preferred_backend": envelope.preferred_backend.value
                if envelope.preferred_backend is not None
                else None,
                "allowed_backends": [backend.value for backend in envelope.allowed_backends],
            },
        )
        preflight = await self._resolve_available_backend(envelope, selection, reporter)
        if isinstance(preflight, AgentTaskResult):
            return preflight
        if preflight.rerouted_from is not None:
            await _publish_state(
                reporter,
                state=TaskState.REROUTED,
                message=(
                    f"Backend rerouted from {preflight.rerouted_from.value} "
                    f"to {preflight.backend.value}."
                ),
                payload={
                    "backend": preflight.backend.value,
                    "rerouted_from": preflight.rerouted_from.value,
                    "reason_codes": [reason.value for reason in preflight.reason_codes],
                },
            )
        await _publish_state(
            reporter,
            state=TaskState.READY_TO_RUN,
            message=f"{preflight.backend.value} is ready to run through OpenCode.",
            payload={
                "backend": preflight.backend.value,
                "reason_codes": [reason.value for reason in preflight.reason_codes],
            },
        )
        await _publish_state(
            reporter,
            state=TaskState.RUNNING,
            message=f"Executing with OpenCode on {preflight.backend.value}.",
            payload={"backend": preflight.backend.value},
        )
        if self._dry_run:
            return self._build_dry_run_result(envelope, preflight)

        argv = shlex.split(self._command)
        if not argv:
            raise OpenCodeRoutingError("OpenCode command is not configured.")
        command_result = await self._runner.run(
            argv,
            stdin=self._build_work_package(envelope, preflight.backend).model_dump_json(),
        )
        if command_result.exit_code != 0:
            return self._build_rate_limited_or_error_result(
                envelope=envelope,
                backend=preflight.backend,
                stderr=command_result.stderr.strip() or command_result.stdout.strip(),
            )
        try:
            payload = json.loads(command_result.stdout)
        except json.JSONDecodeError as exc:
            raise OpenCodeRoutingError("OpenCode command returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise OpenCodeRoutingError("OpenCode command returned a non-object JSON payload.")
        if payload.get("status") in {"rate_limited", "deferred_until_reset"}:
            return AgentTaskResult(
                state=TaskState.DEFERRED_UNTIL_RESET,
                backend=preflight.backend,
                execution_mode=ExecutionMode.OPENCODE,
                summary=payload.get("summary", "Execution deferred until backend reset."),
                reason_code=str(
                    payload.get("reason_code") or ReasonCode.RUNTIME_RATE_LIMITED.value
                ),
                retry_after=_coerce_datetime(payload.get("retry_after") or payload.get("reset_at")),
                raw_output=payload,
                metrics={"executor": "opencode"},
            )
        return AgentTaskResult.model_validate(
            {
                "state": TaskState.COMPLETED,
                "backend": payload.get("backend", preflight.backend.value),
                "execution_mode": ExecutionMode.OPENCODE,
                "summary": payload.get("summary", "OpenCode task finished."),
                "reason_code": None,
                "raw_output": payload,
                "artifacts": payload.get("artifacts", []),
                "metrics": payload.get("metrics", {}),
                "completed_at": payload.get("completed_at"),
            }
        )

    def _select_backend(self, envelope: AgentTaskEnvelope) -> BackendSelection:
        preferred = envelope.preferred_backend or envelope.allowed_backends[0]
        if (
            envelope.task_class
            in {
                TaskClass.CLASSIFY_ONLY,
                TaskClass.PLAN_ONLY,
                TaskClass.SUMMARIZE,
                TaskClass.INSPECT_REPO,
            }
            and BackendName.LOCAL_LLM in envelope.allowed_backends
        ):
            return BackendSelection(
                backend=BackendName.LOCAL_LLM,
                reason_codes=[ReasonCode.TASK_CLASS_MATCH, ReasonCode.LOCAL_LLM_SUFFICIENT],
            )
        if envelope.task_class in {TaskClass.IMPLEMENT, TaskClass.DEBUG, TaskClass.REVIEW}:
            if BackendName.CODEX in envelope.allowed_backends:
                return BackendSelection(
                    backend=BackendName.CODEX,
                    reason_codes=[ReasonCode.TASK_CLASS_MATCH, ReasonCode.REPO_CONTEXT_REQUIRED],
                )
        return BackendSelection(
            backend=preferred,
            reason_codes=[ReasonCode.TASK_CLASS_MATCH],
        )

    async def _resolve_available_backend(
        self,
        envelope: AgentTaskEnvelope,
        selection: BackendSelection,
        reporter: TaskProgressReporter,
    ) -> BackendSelection | AgentTaskResult:
        candidates = [selection.backend]
        if (
            BackendName.COPILOT_CLI in envelope.allowed_backends
            and selection.backend != BackendName.COPILOT_CLI
        ):
            candidates.append(BackendName.COPILOT_CLI)
        if (
            BackendName.LOCAL_LLM in envelope.allowed_backends
            and selection.backend != BackendName.LOCAL_LLM
        ):
            candidates.append(BackendName.LOCAL_LLM)

        deferred_until: datetime | None = None
        for index, backend in enumerate(candidates):
            preflight = await self._preflight_backend(envelope, backend)
            await reporter.publish(
                "agent.task.preflight.checked",
                f"Preflight checked {backend.value}.",
                {
                    "backend": backend.value,
                    "available": preflight.available,
                    "reason_code": preflight.reason_code.value,
                    "retry_after": preflight.retry_after.isoformat()
                    if preflight.retry_after is not None
                    else None,
                },
            )
            if preflight.available:
                reason_codes = list(selection.reason_codes)
                if backend == BackendName.CODEX:
                    reason_codes.append(ReasonCode.CODEX_AVAILABLE)
                elif backend == BackendName.COPILOT_CLI:
                    reason_codes.append(ReasonCode.COPILOT_AVAILABLE)
                elif (
                    backend == BackendName.LOCAL_LLM
                    and ReasonCode.LOCAL_LLM_SUFFICIENT not in reason_codes
                ):
                    reason_codes.append(ReasonCode.LOCAL_LLM_SUFFICIENT)
                return BackendSelection(
                    backend=backend,
                    reason_codes=reason_codes,
                    rerouted_from=selection.backend if index > 0 else None,
                )
            if preflight.retry_after is not None and (
                deferred_until is None or preflight.retry_after > deferred_until
            ):
                deferred_until = preflight.retry_after

        return AgentTaskResult(
            state=TaskState.DEFERRED_UNTIL_RESET,
            backend=selection.backend,
            execution_mode=ExecutionMode.OPENCODE,
            summary="No backend is currently available. Task deferred until reset.",
            reason_code=ReasonCode.BACKEND_UNAVAILABLE.value,
            retry_after=deferred_until,
            raw_output={
                "backend": selection.backend.value,
                "reason_codes": [ReasonCode.BACKEND_UNAVAILABLE.value],
            },
            metrics={"executor": "opencode"},
        )

    async def _preflight_backend(
        self,
        envelope: AgentTaskEnvelope,
        backend: BackendName,
    ) -> PreflightStatus:
        if self._dry_run:
            return PreflightStatus(
                backend=backend,
                available=True,
                reason_code=_availability_reason_code(backend, available=True),
            )

        argv = shlex.split(self._command)
        if not argv:
            raise OpenCodeRoutingError("OpenCode command is not configured.")
        command_result = await self._runner.run(
            [*argv, "preflight"],
            stdin=json.dumps(
                {
                    "backend": backend.value,
                    "task_id": envelope.task_id,
                    "task_class": envelope.task_class.value,
                    "repo": envelope.target_repo,
                }
            ),
        )
        if command_result.exit_code != 0:
            return PreflightStatus(
                backend=backend,
                available=False,
                reason_code=_availability_reason_code(backend, available=False),
                retry_after=datetime.now(UTC) + timedelta(minutes=15),
            )
        try:
            payload = json.loads(command_result.stdout)
        except json.JSONDecodeError as exc:
            raise OpenCodeRoutingError("OpenCode preflight returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise OpenCodeRoutingError("OpenCode preflight returned a non-object JSON payload.")
        return PreflightStatus(
            backend=backend,
            available=bool(payload.get("available", False)),
            reason_code=ReasonCode(
                str(
                    payload.get("reason_code")
                    or _availability_reason_code(
                        backend, available=bool(payload.get("available", False))
                    ).value
                )
            ),
            retry_after=_coerce_datetime(payload.get("retry_after") or payload.get("reset_at")),
        )

    def _build_dry_run_result(
        self,
        envelope: AgentTaskEnvelope,
        selection: BackendSelection,
    ) -> AgentTaskResult:
        summary = (
            f"OpenCode routed {envelope.task_class.value} to "
            f"{selection.backend.value} in dry-run mode for "
            f"{envelope.target_repo or 'default'}."
        )
        artifact_type = (
            "summary" if selection.backend == BackendName.LOCAL_LLM else "execution_result"
        )
        content = (
            {
                "markdown": (
                    f"# {envelope.task_class.value}\n\n{summary}\n\nPrompt:\n{envelope.user_prompt}"
                )
            }
            if selection.backend == BackendName.LOCAL_LLM
            else {
                "provider": selection.backend.value,
                "branch_name": envelope.target_branch or f"agent-task/{envelope.task_id}",
                "commit_shas": [envelope.task_id[:12]],
                "pr_title": f"[{selection.backend.value}] {envelope.user_prompt[:64]}",
                "pr_body": (
                    "Opened by agent service via OpenCode.\n\n"
                    f"Run: {envelope.run_id}\n"
                    f"Repo: {envelope.target_repo or 'default'}\n"
                    f"Backend: {selection.backend.value}"
                ),
                "pr_url": f"https://{settings.git_provider_name}.local/{envelope.target_repo or 'default'}/pull/{envelope.task_id[:8]}",
                "pr_number": int(sha256(envelope.task_id.encode("utf-8")).hexdigest()[:6], 16),
                "execution_summary": summary,
                "known_risks": ["Dry-run OpenCode executor did not invoke a real backend session."],
            }
        )
        return AgentTaskResult(
            state=TaskState.COMPLETED,
            backend=selection.backend,
            execution_mode=ExecutionMode.OPENCODE,
            summary=summary,
            raw_output={
                "mode": "dry_run",
                "command": self._command,
                "task_class": envelope.task_class.value,
                "backend": selection.backend.value,
                "reason_codes": [reason.value for reason in selection.reason_codes],
                "rerouted_from": selection.rerouted_from.value
                if selection.rerouted_from is not None
                else None,
            },
            artifacts=[
                TaskArtifact(
                    artifact_type=artifact_type,
                    title="Task Result",
                    content=content,
                    provenance={"backend": selection.backend.value, "executor": "opencode"},
                    status="completed",
                )
            ],
            metrics={"mode": "dry_run", "executor": "opencode"},
            completed_at=datetime.now(UTC),
        )

    def _build_work_package(
        self,
        envelope: AgentTaskEnvelope,
        backend: BackendName,
    ) -> ExecutorWorkPackage:
        return ExecutorWorkPackage(
            run_id=envelope.run_id,
            backend=backend.value,
            repo=envelope.target_repo or "default",
            project=ProjectContext(project_path=envelope.metadata.get("project_path")),
            branch_strategy=envelope.target_branch or f"agent-task/{envelope.task_id}",
            instructions=envelope.user_prompt,
            constraints=[
                f"task_class={envelope.task_class.value}",
                f"execution_mode={envelope.execution_mode.value}",
            ],
            acceptance_criteria=_acceptance_criteria_for_task(envelope.task_class),
            source_metadata={
                "task_id": envelope.task_id,
                "correlation_id": envelope.correlation_id,
                "route_profile": envelope.dispatch.route_profile,
                "allowed_backends": [candidate.value for candidate in envelope.allowed_backends],
                "preferred_backend": envelope.preferred_backend.value
                if envelope.preferred_backend is not None
                else None,
                "execution_target": envelope.dispatch.target_id,
                "metadata": envelope.metadata,
                "approval_policy": envelope.approval_policy,
                "timeout_policy": envelope.timeout_policy,
                "return_artifacts": envelope.return_artifacts,
            },
        )

    def _build_rate_limited_or_error_result(
        self,
        *,
        envelope: AgentTaskEnvelope,
        backend: BackendName,
        stderr: str,
    ) -> AgentTaskResult:
        normalized = stderr.lower()
        if "rate limit" in normalized or "rate_limit" in normalized:
            return AgentTaskResult(
                state=TaskState.DEFERRED_UNTIL_RESET,
                backend=backend,
                execution_mode=ExecutionMode.OPENCODE,
                summary=f"{backend.value} hit a runtime rate limit. Task deferred.",
                reason_code=ReasonCode.RUNTIME_RATE_LIMITED.value,
                retry_after=datetime.now(UTC) + timedelta(minutes=15),
                raw_output={"error": stderr},
                metrics={"executor": "opencode"},
            )
        return AgentTaskResult(
            state=TaskState.FAILED,
            backend=backend,
            execution_mode=ExecutionMode.OPENCODE,
            summary=f"OpenCode execution failed for {backend.value}.",
            reason_code="execution_failed",
            raw_output={"error": stderr},
            metrics={"executor": "opencode"},
            completed_at=datetime.now(UTC),
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
                f"{envelope.execution_mode.value} selected worker "
                f"{envelope.dispatch.target_id} with preferred backend "
                f"{envelope.preferred_backend.value if envelope.preferred_backend else 'none'}."
            ),
            {
                "state": TaskState.QUEUED.value,
                "execution_mode": envelope.execution_mode.value,
                "dispatch_target": envelope.dispatch.target_id,
                "preferred_backend": envelope.preferred_backend.value
                if envelope.preferred_backend is not None
                else None,
                "allowed_backends": [backend.value for backend in envelope.allowed_backends],
            },
        )
        return await self._executor.execute(envelope, reporter)


def classify_task(prompt: str) -> TaskClass:
    lowered = prompt.lower()
    if any(token in lowered for token in {"summarize", "summary"}):
        return TaskClass.SUMMARIZE
    if "plan" in lowered:
        return TaskClass.PLAN_ONLY
    if "classify" in lowered:
        return TaskClass.CLASSIFY_ONLY
    if "review" in lowered:
        return TaskClass.REVIEW
    if "debug" in lowered:
        return TaskClass.DEBUG
    if "inspect" in lowered:
        return TaskClass.INSPECT_REPO
    return TaskClass.IMPLEMENT


def normalize_goal(prompt: str) -> str:
    return " ".join(prompt.split()).strip()


def default_allowed_backends_for_task(task_class: TaskClass) -> list[BackendName]:
    if task_class in {
        TaskClass.CLASSIFY_ONLY,
        TaskClass.PLAN_ONLY,
        TaskClass.SUMMARIZE,
        TaskClass.INSPECT_REPO,
    }:
        return [BackendName.LOCAL_LLM, BackendName.CODEX, BackendName.COPILOT_CLI]
    return [BackendName.CODEX, BackendName.COPILOT_CLI, BackendName.LOCAL_LLM]


def default_preferred_backend_for_task(task_class: TaskClass) -> BackendName:
    if task_class in {
        TaskClass.CLASSIFY_ONLY,
        TaskClass.PLAN_ONLY,
        TaskClass.SUMMARIZE,
        TaskClass.INSPECT_REPO,
    }:
        return BackendName.LOCAL_LLM
    return BackendName.CODEX


def available_route_profiles(task_class: TaskClass) -> Sequence[str]:
    if task_class in {
        TaskClass.CLASSIFY_ONLY,
        TaskClass.PLAN_ONLY,
        TaskClass.SUMMARIZE,
        TaskClass.INSPECT_REPO,
    }:
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


async def _publish_state(
    reporter: TaskProgressReporter,
    *,
    state: TaskState,
    message: str,
    payload: dict | None = None,
) -> None:
    await reporter.publish(
        "agent.task.state_changed",
        message,
        {"state": state.value, **(payload or {})},
    )


def _availability_reason_code(backend: BackendName, *, available: bool) -> ReasonCode:
    if backend == BackendName.CODEX:
        return ReasonCode.CODEX_AVAILABLE if available else ReasonCode.CODEX_RATE_LIMITED
    if backend == BackendName.COPILOT_CLI:
        return ReasonCode.COPILOT_AVAILABLE
    return ReasonCode.LOCAL_LLM_SUFFICIENT


def _coerce_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
