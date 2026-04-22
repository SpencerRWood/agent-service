import asyncio

from app.integrations.providers.runner import CommandExecutionResult
from app.platform.agent_tasks.contracts import ExecutorWorkPackage, ProjectContext
from app.platform.agent_tasks.opencode_adapter import OpenCodeCLIAdapter
from app.platform.agent_tasks.schemas import BackendName, ReasonCode


class FakeRunner:
    def __init__(self, results: list[CommandExecutionResult]) -> None:
        self._results = list(results)
        self.calls: list[tuple[list[str], str | None]] = []

    async def run(self, argv: list[str], *, stdin: str | None = None) -> CommandExecutionResult:
        self.calls.append((argv, stdin))
        if not self._results:
            raise AssertionError("Unexpected command invocation")
        return self._results.pop(0)


def build_work_package() -> ExecutorWorkPackage:
    return ExecutorWorkPackage(
        run_id="run-1",
        backend="codex",
        repo="agent-service",
        project=ProjectContext(project_path="/tmp/project"),
        branch_strategy="agent-task/run-1",
        instructions="Inspect the repository and answer briefly.",
        constraints=["task_class=inspect_repo", "execution_mode=opencode"],
        acceptance_criteria=["The user question is answered directly and concisely."],
        source_metadata={"task_id": "task-1"},
    )


def test_preflight_uses_real_run_help_contract():
    runner = FakeRunner(
        [CommandExecutionResult(exit_code=0, stdout="usage: opencode run", stderr="")]
    )
    adapter = OpenCodeCLIAdapter(command="/bin/echo", runner=runner)

    result = asyncio.run(
        adapter.preflight(
            backend=BackendName.CODEX,
            task_id="task-1",
            task_class="inspect_repo",
            repo="agent-service",
        )
    )

    assert result.available is True
    assert result.reason_code == ReasonCode.CODEX_AVAILABLE
    assert runner.calls == [(["/bin/echo", "run", "--help"], None)]


def test_execute_parses_json_events_into_summary_and_artifact():
    runner = FakeRunner(
        [
            CommandExecutionResult(
                exit_code=0,
                stdout=(
                    '{"type":"session.started"}\n'
                    '{"type":"message","message":{"content":"The stream path is '
                    '/api/agent-tasks/{task_id}/stream."}}\n'
                ),
                stderr="",
            )
        ]
    )
    adapter = OpenCodeCLIAdapter(command="/bin/echo", runner=runner)

    payload = asyncio.run(
        adapter.execute(
            work_package=build_work_package(),
            backend=BackendName.CODEX,
        )
    )

    assert payload["backend"] == "codex"
    assert payload["summary"] == "The stream path is /api/agent-tasks/{task_id}/stream."
    assert payload["artifacts"][0]["title"] == "Task Result"
    argv, stdin = runner.calls[0]
    assert argv[:4] == ["/bin/echo", "run", "--format", "json"]
    assert "--dir" in argv
    assert stdin is None


def test_execute_uses_envelope_model_override():
    runner = FakeRunner(
        [
            CommandExecutionResult(
                exit_code=0,
                stdout='{"type":"text","part":{"type":"text","text":"ok"}}\n',
                stderr="",
            )
        ]
    )
    adapter = OpenCodeCLIAdapter(command="/bin/echo", runner=runner)

    asyncio.run(
        adapter.execute(
            work_package=build_work_package(),
            backend=BackendName.CODEX,
            model_overrides={"codex": "openrouter/openai/gpt-oss-120b:free"},
        )
    )

    argv, _ = runner.calls[0]
    assert "--model" in argv
    assert "openrouter/openai/gpt-oss-120b:free" in argv


def test_execute_prefers_explicit_text_parts_over_session_ids():
    runner = FakeRunner(
        [
            CommandExecutionResult(
                exit_code=0,
                stdout=(
                    '{"type":"step_start","sessionID":"ses_123","part":{"type":"step-start"}}\n'
                    '{"type":"text","sessionID":"ses_123","part":{"type":"text","text":"adapter-ok"}}\n'
                    '{"type":"step_finish","sessionID":"ses_123","part":{"type":"step-finish"}}\n'
                ),
                stderr="",
            )
        ]
    )
    adapter = OpenCodeCLIAdapter(command="/bin/echo", runner=runner)

    payload = asyncio.run(
        adapter.execute(
            work_package=build_work_package(),
            backend=BackendName.CODEX,
        )
    )

    assert payload["summary"] == "adapter-ok"


def test_execute_extracts_structured_workflow_outcome():
    runner = FakeRunner(
        [
            CommandExecutionResult(
                exit_code=0,
                stdout=(
                    '{"type":"message","message":{"content":"review finished"}}\n'
                    '{"type":"result","workflow_outcome":"needs_changes"}\n'
                ),
                stderr="",
            )
        ]
    )
    adapter = OpenCodeCLIAdapter(command="/bin/echo", runner=runner)

    payload = asyncio.run(
        adapter.execute(
            work_package=build_work_package(),
            backend=BackendName.CODEX,
        )
    )

    assert payload["workflow_outcome"] == "needs_changes"
