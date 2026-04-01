import asyncio

from app.features.orchestration.models import ProviderName
from app.features.orchestration.schemas import ApprovedWorkPackage, WorkerTarget
from app.integrations.providers.codex import CodexProvider
from app.integrations.providers.copilot_cli import CopilotCliProvider
from app.integrations.providers.runner import CommandExecutionResult


class FakeCommandRunner:
    def __init__(self, result: CommandExecutionResult) -> None:
        self.result = result
        self.calls: list[tuple[list[str], str | None]] = []

    async def run(self, argv: list[str], *, stdin: str | None = None) -> CommandExecutionResult:
        self.calls.append((argv, stdin))
        return self.result


def build_work_package() -> ApprovedWorkPackage:
    return ApprovedWorkPackage(
        run_id="run-123",
        approval_id=1,
        provider=ProviderName.CODEX,
        repo="agent-service",
        worker_target=WorkerTarget.WORKER_B,
        branch_strategy="orchestration/agent-service/default/worker-b/run-123",
        instructions="Add orchestration wiring",
        constraints=["Use adapters"],
        acceptance_criteria=["Open a PR"],
        source_metadata={"source": "test"},
    )


def test_codex_provider_uses_runner_in_non_dry_mode():
    runner = FakeCommandRunner(
        CommandExecutionResult(
            exit_code=0,
            stdout=(
                '{"branch_name":"feature/test","commit_shas":["abc123"],'
                '"pr_title":"PR","pr_body":"Body","pr_url":"https://git/pull/1",'
                '"pr_number":1,"execution_summary":"done","known_risks":[]}'
            ),
            stderr="",
        )
    )
    provider = CodexProvider(command="codex-adapter", dry_run=False, runner=runner)

    result = asyncio.run(provider.execute(build_work_package()))

    assert runner.calls == [(["codex-adapter"], build_work_package().model_dump_json())]
    assert result.provider == "codex"
    assert result.worker_target == WorkerTarget.WORKER_B
    assert result.branch_name == "feature/test"


def test_copilot_provider_dry_run_still_returns_synthetic_result():
    provider = CopilotCliProvider(command="copilot-adapter", dry_run=True)

    result = asyncio.run(provider.execute(build_work_package().model_copy(update={"provider": ProviderName.COPILOT_CLI})))

    assert result.provider == "copilot_cli"
    assert result.branch_name == "orchestration/agent-service/default/worker-b/run-123"
    assert "Configured command: copilot-adapter" in result.execution_summary
