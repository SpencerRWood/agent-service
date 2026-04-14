from __future__ import annotations

import json
import shlex
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.settings import settings
from app.integrations.providers.runner import CommandExecutionResult, CommandRunner
from app.platform.agent_tasks.contracts import ExecutorWorkPackage
from app.platform.agent_tasks.schemas import BackendName, ReasonCode


@dataclass(slots=True)
class OpenCodePreflightResult:
    available: bool
    reason_code: ReasonCode
    retry_after: datetime | None = None
    detail: str | None = None


class OpenCodeAdapterError(RuntimeError):
    """Raised when the installed OpenCode CLI cannot satisfy the adapter contract."""


class OpenCodeCLIAdapter:
    def __init__(
        self,
        *,
        command: str | None = None,
        runner: CommandRunner,
    ) -> None:
        self._command = command or settings.opencode_command
        self._runner = runner

    async def preflight(
        self,
        *,
        backend: BackendName,
        task_id: str,
        task_class: str,
        repo: str | None,
    ) -> OpenCodePreflightResult:
        argv = shlex.split(self._command)
        if not argv:
            return OpenCodePreflightResult(
                available=False,
                reason_code=_availability_reason_code(backend, available=False),
                retry_after=datetime.now(UTC) + timedelta(minutes=15),
                detail="OpenCode command is not configured.",
            )

        executable = argv[0]
        if shutil.which(executable) is None and not executable.startswith("/"):
            return OpenCodePreflightResult(
                available=False,
                reason_code=_availability_reason_code(backend, available=False),
                retry_after=datetime.now(UTC) + timedelta(minutes=15),
                detail=f"OpenCode executable '{executable}' was not found.",
            )

        # Use the real installed CLI contract instead of the previously assumed
        # custom `preflight` subcommand. `run --help` is stable, fast, and
        # validates that the command is callable in the current environment.
        command_result = await self._runner.run([*argv, "run", "--help"])
        if command_result.exit_code != 0:
            return OpenCodePreflightResult(
                available=False,
                reason_code=_availability_reason_code(backend, available=False),
                retry_after=datetime.now(UTC) + timedelta(minutes=15),
                detail=_combine_output(command_result),
            )

        return OpenCodePreflightResult(
            available=True,
            reason_code=_availability_reason_code(backend, available=True),
        )

    async def execute(
        self,
        *,
        work_package: ExecutorWorkPackage,
        backend: BackendName,
    ) -> dict[str, Any]:
        argv = shlex.split(self._command)
        if not argv:
            raise OpenCodeAdapterError("OpenCode command is not configured.")

        command_result = await self._runner.run(
            self._build_run_argv(argv, work_package=work_package, backend=backend)
        )
        if command_result.exit_code != 0:
            raise OpenCodeAdapterError(_combine_output(command_result))

        events = _parse_json_lines(command_result.stdout)
        if not events:
            raise OpenCodeAdapterError(
                "OpenCode run returned no JSON events. "
                f"stdout={command_result.stdout.strip()!r} stderr={command_result.stderr.strip()!r}"
            )

        extracted_text = _extract_text_from_events(events)
        summary = extracted_text or "OpenCode task finished."
        return {
            "backend": backend.value,
            "summary": summary,
            "artifacts": [
                {
                    "artifact_type": "execution_result",
                    "title": "Task Result",
                    "content": {"markdown": summary},
                    "provenance": {"backend": backend.value, "executor": "opencode"},
                    "status": "completed",
                }
            ],
            "metrics": {"executor": "opencode", "format": "json_events"},
            "events": events,
            "completed_at": datetime.now(UTC).isoformat(),
        }

    def _build_run_argv(
        self,
        argv: list[str],
        *,
        work_package: ExecutorWorkPackage,
        backend: BackendName,
    ) -> list[str]:
        run_argv = [*argv, "run", "--format", "json"]
        model_override = settings.opencode_backend_models.get(backend.value)
        if model_override:
            run_argv.extend(["--model", model_override])
        project_path = work_package.project.project_path if work_package.project else None
        if project_path:
            run_argv.extend(["--dir", project_path])
        run_argv.append(_render_message(work_package, backend))
        return run_argv


def _render_message(work_package: ExecutorWorkPackage, backend: BackendName) -> str:
    constraints = "\n".join(f"- {item}" for item in work_package.constraints)
    acceptance = "\n".join(f"- {item}" for item in work_package.acceptance_criteria)
    return (
        f"Backend hint: {backend.value}\n"
        f"Repo: {work_package.repo}\n"
        f"Branch strategy: {work_package.branch_strategy}\n\n"
        f"Instructions:\n{work_package.instructions}\n\n"
        f"Constraints:\n{constraints or '- none'}\n\n"
        f"Acceptance criteria:\n{acceptance or '- none'}"
    )


def _parse_json_lines(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _extract_text_from_events(events: list[dict[str, Any]]) -> str | None:
    explicit_texts: list[str] = []
    for event in events:
        if event.get("type") == "text":
            part = event.get("part")
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    explicit_texts.append(text.strip())
    if explicit_texts:
        return explicit_texts[-1]

    strings: list[str] = []
    for event in events:
        _collect_strings(event, strings)
    unique = [value for value in strings if value.strip()]
    if not unique:
        return None
    # Prefer the last substantial string, which is typically closest to the final answer.
    for candidate in reversed(unique):
        normalized = candidate.strip()
        if len(normalized) >= 20:
            return normalized
    return unique[-1].strip()


def _collect_strings(value: Any, output: list[str]) -> None:
    if isinstance(value, str):
        output.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _collect_strings(item, output)
        return
    if isinstance(value, dict):
        for key in ("text", "content", "markdown", "message", "summary", "output", "answer"):
            if key in value:
                _collect_strings(value[key], output)
        for nested in value.values():
            _collect_strings(nested, output)


def _combine_output(result: CommandExecutionResult) -> str:
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    if stderr and stdout:
        return f"{stderr}\n{stdout}"
    return stderr or stdout or "OpenCode command failed without output."


def _availability_reason_code(backend: BackendName, *, available: bool) -> ReasonCode:
    if available:
        if backend == BackendName.CODEX:
            return ReasonCode.CODEX_AVAILABLE
        if backend == BackendName.COPILOT_CLI:
            return ReasonCode.COPILOT_AVAILABLE
        return ReasonCode.LOCAL_LLM_SUFFICIENT
    if backend == BackendName.CODEX:
        return ReasonCode.CODEX_RATE_LIMITED
    return ReasonCode.BACKEND_UNAVAILABLE
