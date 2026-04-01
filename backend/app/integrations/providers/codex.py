from __future__ import annotations

from uuid import uuid4

from app.core.settings import settings
from app.features.orchestration.schemas import ApprovedWorkPackage, WorkerExecutionResult


class CodexProvider:
    provider_name = "codex"

    async def execute(self, work_package: ApprovedWorkPackage) -> WorkerExecutionResult:
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
            execution_summary="Codex provider executed the approved work package in dry-run mode.",
            known_risks=["Dry-run provider did not invoke a real Codex CLI session."],
        )
