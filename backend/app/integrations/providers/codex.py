from __future__ import annotations

import json
import shlex
from uuid import uuid4

from app.core.settings import settings
from app.features.orchestration.schemas import ApprovedWorkPackage, WorkerExecutionResult
from app.integrations.providers.base import ProviderExecutionError
from app.integrations.providers.runner import CommandRunner, SubprocessCommandRunner


class CodexProvider:
    provider_name = "codex"

    def __init__(
        self,
        *,
        command: str | None = None,
        dry_run: bool | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self._command = command or settings.codex_command
        self._dry_run = settings.orchestration_dry_run if dry_run is None else dry_run
        self._runner = runner or SubprocessCommandRunner()

    async def execute(self, work_package: ApprovedWorkPackage) -> WorkerExecutionResult:
        if self._dry_run:
            return self._build_dry_run_result(work_package)

        argv = shlex.split(self._command)
        if not argv:
            raise ProviderExecutionError("Codex command is not configured.")

        command_result = await self._runner.run(argv, stdin=work_package.model_dump_json())
        if command_result.exit_code != 0:
            raise ProviderExecutionError(
                "Codex command failed "
                f"(exit {command_result.exit_code}): {command_result.stderr.strip() or command_result.stdout.strip()}"
            )

        try:
            payload = json.loads(command_result.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderExecutionError("Codex command returned invalid JSON.") from exc

        if not isinstance(payload, dict):
            raise ProviderExecutionError("Codex command returned a non-object JSON payload.")

        payload.setdefault("provider", self.provider_name)
        payload.setdefault("worker_target", work_package.worker_target.value)
        return WorkerExecutionResult.model_validate(payload)

    def _build_dry_run_result(self, work_package: ApprovedWorkPackage) -> WorkerExecutionResult:
        suffix = uuid4().hex[:8]
        branch_name = work_package.branch_strategy
        return WorkerExecutionResult(
            provider=self.provider_name,
            worker_target=work_package.worker_target,
            branch_name=branch_name,
            commit_shas=[uuid4().hex[:12]],
            pr_title=f"[Codex] {work_package.instructions[:72]}",
            pr_body=(
                "Opened by orchestration service via Codex provider.\n\n"
                f"Run: {work_package.run_id}\n"
                f"Repo: {work_package.repo}\n"
                f"Target: {work_package.worker_target.value}"
            ),
            pr_url=(
                f"https://{settings.git_provider_name}.local/"
                f"{work_package.repo}/pull/{suffix}"
            ),
            pr_number=int(suffix[:6], 16),
            execution_summary=(
                "Codex provider executed the approved work package in dry-run mode. "
                f"Configured command: {self._command}"
            ),
            known_risks=[
                "Dry-run provider did not invoke a real Codex CLI session.",
            ],
        )
