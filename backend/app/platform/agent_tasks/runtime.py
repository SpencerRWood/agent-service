from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Protocol

from app.core.settings import settings
from app.integrations.providers.runner import CommandRunner, SubprocessCommandRunner
from app.platform.agent_tasks.contracts import ExecutorWorkPackage, ProjectContext
from app.platform.agent_tasks.opencode_adapter import OpenCodeCLIAdapter
from app.platform.agent_tasks.schemas import (
    AgentTaskEnvelope,
    AgentTaskResult,
    BackendName,
    ExecutionMode,
    ReasonCode,
    TaskArtifact,
    TaskClass,
    TaskState,
    WorkflowOutcome,
)


class TaskProgressReporter(Protocol):
    async def publish(self, event_type: str, message: str, payload: dict | None = None) -> None: ...

    async def publish_artifact(self, artifact: TaskArtifact) -> None: ...


class OpenCodeProgressReporter:
    """Reporter that sends progress events to the broker's progress endpoint."""

    def __init__(
        self,
        *,
        task_id: str,
        run_id: str,
        step_id: str,
        correlation_id: str,
        base_url: str,
    ) -> None:
        self._task_id = task_id
        self._run_id = run_id
        self._step_id = step_id
        self._correlation_id = correlation_id
        self._base_url = base_url.rstrip("/")

    async def publish(
        self,
        event_type: str,
        message: str,
        payload: dict | None = None,
    ) -> None:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                await client.post(
                    f"{self._base_url}/api/worker/agent-tasks/{self._task_id}/progress",
                    json={
                        "run_id": self._run_id,
                        "step_id": self._step_id,
                        "correlation_id": self._correlation_id,
                        "event_type": event_type,
                        "message": message,
                        "payload": payload or {},
                        "actor_type": "worker",
                        "actor_id": "opencode-runtime",
                    },
                )
            except Exception:
                pass

    async def publish_artifact(self, artifact: TaskArtifact) -> None:
        pass


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
        self._adapter = OpenCodeCLIAdapter(command=self._command, runner=self._runner)

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

        try:
            payload = await self._adapter.execute(
                work_package=self._build_work_package(envelope, preflight.backend),
                backend=preflight.backend,
            )
        except OpenCodeRoutingError:
            raise
        except Exception as exc:
            return self._build_rate_limited_or_error_result(
                envelope=envelope,
                backend=preflight.backend,
                stderr=str(exc),
            )
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
                completed_at=datetime.now(UTC),
            )
        return AgentTaskResult.model_validate(
            {
                "state": TaskState.COMPLETED,
                "backend": payload.get("backend", preflight.backend.value),
                "execution_mode": ExecutionMode.OPENCODE,
                "summary": payload.get("summary", "OpenCode task finished."),
                "workflow_outcome": payload.get("workflow_outcome"),
                "reason_code": None,
                "raw_output": payload,
                "artifacts": payload.get("artifacts", []),
                "metrics": payload.get("metrics", {}),
                "completed_at": payload.get("completed_at"),
            }
        )

    def _select_backend(self, envelope: AgentTaskEnvelope) -> BackendSelection:
        preferred = envelope.preferred_backend or envelope.allowed_backends[0]
        if preferred in envelope.allowed_backends and preferred != BackendName.LOCAL_LLM:
            return BackendSelection(
                backend=preferred,
                reason_codes=[ReasonCode.TASK_CLASS_MATCH],
            )
        if (
            envelope.task_class == TaskClass.INSPECT_REPO
            and preferred == BackendName.CODEX
            and BackendName.CODEX in envelope.allowed_backends
        ):
            return BackendSelection(
                backend=BackendName.CODEX,
                reason_codes=[ReasonCode.TASK_CLASS_MATCH, ReasonCode.REPO_CONTEXT_REQUIRED],
            )
        if (
            envelope.task_class
            in {
                TaskClass.CLASSIFY_ONLY,
                TaskClass.ANSWER_QUESTION,
                TaskClass.PLAN_ONLY,
                TaskClass.SUMMARIZE,
                TaskClass.INSPECT_REPO,
                TaskClass.ANALYZE,
            }
            and BackendName.LOCAL_LLM in envelope.allowed_backends
        ):
            return BackendSelection(
                backend=BackendName.LOCAL_LLM,
                reason_codes=[ReasonCode.TASK_CLASS_MATCH, ReasonCode.LOCAL_LLM_SUFFICIENT],
            )
        if envelope.task_class in {
            TaskClass.IMPLEMENT,
            TaskClass.REFACTOR,
            TaskClass.DEBUG,
            TaskClass.REVIEW,
            TaskClass.TEST,
            TaskClass.DOCUMENT,
        }:
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
        candidates: list[BackendName] = []

        def add_candidate(backend: BackendName) -> None:
            if backend in envelope.allowed_backends and backend not in candidates:
                candidates.append(backend)

        add_candidate(selection.backend)
        add_candidate(BackendName.CODEX)
        add_candidate(BackendName.COPILOT_CLI)
        add_candidate(BackendName.LOCAL_LLM)

        deferred_until: datetime | None = None
        available_alternatives: list[BackendName] = []
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
                if (
                    selection.backend == BackendName.LOCAL_LLM
                    and backend != BackendName.LOCAL_LLM
                    and envelope.task_class
                    in {
                        TaskClass.CLASSIFY_ONLY,
                        TaskClass.ANSWER_QUESTION,
                        TaskClass.PLAN_ONLY,
                        TaskClass.SUMMARIZE,
                        TaskClass.ANALYZE,
                    }
                ):
                    available_alternatives.append(backend)
                    continue
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

        if available_alternatives:
            suggested_backend = available_alternatives[0]
            backend_labels = ", ".join(backend.value for backend in available_alternatives)
            return AgentTaskResult(
                state=TaskState.PENDING_APPROVAL,
                backend=suggested_backend,
                execution_mode=ExecutionMode.OPENCODE,
                summary=(
                    "Local planner backend is unavailable. "
                    f"{backend_labels} is available. Approve to continue with "
                    f"{suggested_backend.value}."
                ),
                reason_code=ReasonCode.BACKEND_UNAVAILABLE.value,
                raw_output={
                    "suggested_backend": suggested_backend.value,
                    "available_backends": [backend.value for backend in available_alternatives],
                },
                metrics={"executor": "opencode"},
            )

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
            completed_at=datetime.now(UTC),
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

        preflight = await self._adapter.preflight(
            backend=backend,
            task_id=envelope.task_id,
            task_class=envelope.task_class.value,
            repo=envelope.target_repo,
        )
        if not preflight.available:
            return PreflightStatus(
                backend=backend,
                available=False,
                reason_code=preflight.reason_code,
                retry_after=preflight.retry_after,
            )
        return PreflightStatus(
            backend=backend,
            available=True,
            reason_code=preflight.reason_code,
            retry_after=preflight.retry_after,
        )

    def _build_dry_run_result(
        self,
        envelope: AgentTaskEnvelope,
        selection: BackendSelection,
    ) -> AgentTaskResult:
        summary = (
            f"OpenCode routed {envelope.public_agent_id or envelope.task_class.value} "
            f"via {envelope.runtime_key or 'default_runtime'} to "
            f"{selection.backend.value} in dry-run mode for "
            f"{envelope.target_repo or 'default'}."
        )
        artifact_type = (
            "summary" if selection.backend == BackendName.LOCAL_LLM else "execution_result"
        )
        content = (
            {
                "markdown": (
                    f"# {envelope.public_agent_id or envelope.task_class.value}\n\n"
                    f"{summary}\n\nPrompt:\n{envelope.user_prompt}"
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
            workflow_outcome=_default_workflow_outcome_for_task(envelope.task_class),
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
            runtime_key=envelope.runtime_key,
            public_agent_id=envelope.public_agent_id,
            agent_system_prompt=envelope.agent_system_prompt,
            project=ProjectContext(project_path=envelope.metadata.get("project_path")),
            branch_strategy=envelope.target_branch or f"agent-task/{envelope.task_id}",
            instructions=envelope.user_prompt,
            constraints=[
                f"task_class={envelope.task_class.value}",
                f"public_agent_id={envelope.public_agent_id or 'none'}",
                f"runtime_key={envelope.runtime_key or 'none'}",
                f"execution_mode={envelope.execution_mode.value}",
            ],
            acceptance_criteria=_acceptance_criteria_for_task(envelope.task_class),
            workflow=envelope.agent_workflow,
            source_metadata={
                "task_id": envelope.task_id,
                "correlation_id": envelope.correlation_id,
                "public_agent_id": envelope.public_agent_id,
                "runtime_key": envelope.runtime_key,
                "agent_system_prompt": envelope.agent_system_prompt,
                "agent_workflow": envelope.agent_workflow,
                "route_profile": envelope.dispatch.route_profile,
                "target_branch": envelope.target_branch,
                "branch_strategy": envelope.target_branch or f"agent-task/{envelope.task_id}",
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
                completed_at=datetime.now(UTC),
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
                f"{envelope.preferred_backend.value if envelope.preferred_backend else 'none'} "
                f"for {envelope.public_agent_id or envelope.task_class.value}."
            ),
            {
                "state": TaskState.QUEUED.value,
                "execution_mode": envelope.execution_mode.value,
                "dispatch_target": envelope.dispatch.target_id,
                "public_agent_id": envelope.public_agent_id,
                "runtime_key": envelope.runtime_key,
                "preferred_backend": envelope.preferred_backend.value
                if envelope.preferred_backend is not None
                else None,
                "allowed_backends": [backend.value for backend in envelope.allowed_backends],
            },
        )
        return await self._executor.execute(envelope, reporter)


def classify_task(prompt: str) -> TaskClass:
    lowered = prompt.lower()
    if any(token in lowered for token in {"readme", "documentation", "document", "docs"}):
        return TaskClass.DOCUMENT
    if any(
        token in lowered
        for token in {"unit test", "integration test", "add tests", "write tests", "test "}
    ):
        return TaskClass.TEST
    if "refactor" in lowered:
        return TaskClass.REFACTOR
    if any(token in lowered for token in {"summarize", "summary"}):
        return TaskClass.SUMMARIZE
    if any(
        token in lowered for token in {"analyze", "analysis", "compare", "tradeoff", "explain why"}
    ):
        return TaskClass.ANALYZE
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
    if lowered.rstrip().endswith("?") or lowered.startswith(
        ("what ", "why ", "how ", "when ", "where ", "who ", "which ")
    ):
        return TaskClass.ANSWER_QUESTION
    return TaskClass.IMPLEMENT


def normalize_goal(prompt: str) -> str:
    return " ".join(prompt.split()).strip()


def default_allowed_backends_for_task(task_class: TaskClass) -> list[BackendName]:
    if task_class in {
        TaskClass.CLASSIFY_ONLY,
        TaskClass.ANSWER_QUESTION,
        TaskClass.PLAN_ONLY,
        TaskClass.SUMMARIZE,
        TaskClass.INSPECT_REPO,
        TaskClass.ANALYZE,
    }:
        return [BackendName.LOCAL_LLM, BackendName.CODEX, BackendName.COPILOT_CLI]
    return [BackendName.CODEX, BackendName.COPILOT_CLI, BackendName.LOCAL_LLM]


def default_preferred_backend_for_task(task_class: TaskClass) -> BackendName:
    if task_class in {
        TaskClass.CLASSIFY_ONLY,
        TaskClass.ANSWER_QUESTION,
        TaskClass.PLAN_ONLY,
        TaskClass.SUMMARIZE,
        TaskClass.INSPECT_REPO,
        TaskClass.ANALYZE,
    }:
        return BackendName.LOCAL_LLM
    return BackendName.CODEX


def available_route_profiles(task_class: TaskClass) -> Sequence[str]:
    if task_class in {
        TaskClass.CLASSIFY_ONLY,
        TaskClass.ANSWER_QUESTION,
        TaskClass.PLAN_ONLY,
        TaskClass.SUMMARIZE,
        TaskClass.INSPECT_REPO,
        TaskClass.ANALYZE,
    }:
        return ("cheap", "local")
    return ("implementation", "coding")


def _acceptance_criteria_for_task(task_class: TaskClass) -> list[str]:
    if task_class == TaskClass.IMPLEMENT:
        return ["Requested implementation is completed and summarized."]
    if task_class == TaskClass.REFACTOR:
        return ["Requested refactor is completed without changing intended behavior."]
    if task_class == TaskClass.DEBUG:
        return ["Root cause is identified and a fix is proposed or applied."]
    if task_class == TaskClass.REVIEW:
        return ["Review findings are explicit and ordered by severity."]
    if task_class == TaskClass.TEST:
        return ["Relevant tests are added or updated and summarized."]
    if task_class == TaskClass.DOCUMENT:
        return ["Requested documentation is produced or updated clearly."]
    if task_class == TaskClass.INSPECT_REPO:
        return ["Repository structure and constraints are summarized."]
    if task_class == TaskClass.ANALYZE:
        return ["Tradeoffs and conclusions are summarized clearly."]
    if task_class == TaskClass.ANSWER_QUESTION:
        return ["The user question is answered directly and concisely."]
    return ["Task output is returned in a concise final artifact."]


def _default_workflow_outcome_for_task(task_class: TaskClass) -> WorkflowOutcome:
    if task_class == TaskClass.REVIEW:
        return WorkflowOutcome.NEEDS_CHANGES
    return WorkflowOutcome.SUCCESS


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
