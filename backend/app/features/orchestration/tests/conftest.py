from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.settings import settings
from app.features.orchestration.dependencies import get_orchestration_service
from app.features.orchestration.models import (
    ExecutionStatus,
    OrchestrationRun,
    ProviderName,
    PullRequestStatus,
    RagStatus,
    WorkerType,
)
from app.features.orchestration.router import router, tool_router, webhook_router
from app.features.orchestration.schemas import PullRequestState, WorkerExecutionResult, WorkerTarget
from app.features.orchestration.service import OrchestrationService
from app.integrations.control_hub.client import (
    ControlHubApprovalItemCreate,
    ControlHubApprovalItemRead,
    ControlHubIntegrationError,
)
from app.integrations.providers.base import ProviderExecutionError
from app.integrations.providers.router import PolicyBasedProviderRouter
from app.integrations.rag.client import RagIngestionError, RagIngestionReceipt


class FakeRepository:
    def __init__(self) -> None:
        self.items: dict[str, OrchestrationRun] = {}

    async def create(self, run: OrchestrationRun) -> OrchestrationRun:
        if not run.id:
            run.id = str(uuid4())
        now = datetime.now(UTC)
        if not run.created_at:
            run.created_at = now
        run.updated_at = now
        self.items[run.id] = run
        return run

    async def update(self, run: OrchestrationRun) -> OrchestrationRun:
        run.updated_at = datetime.now(UTC)
        self.items[run.id] = run
        return run

    async def get(self, run_id: str) -> OrchestrationRun | None:
        return self.items.get(run_id)

    async def get_by_repo_and_pr_number(
        self,
        *,
        repo: str,
        pr_number: int,
    ) -> OrchestrationRun | None:
        for run in self.items.values():
            if run.repo == repo and run.pr_number == pr_number:
                return run
        return None

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[OrchestrationRun]:
        runs = list(self.items.values())
        return runs[offset : offset + limit]


class FakeControlHubClient:
    def __init__(self) -> None:
        self._next_id = 1
        self.items: dict[int, ControlHubApprovalItemRead] = {}
        self.fail_create = False
        self.fail_get = False

    async def create_approval(
        self, item: ControlHubApprovalItemCreate
    ) -> ControlHubApprovalItemRead:
        if self.fail_create:
            raise ControlHubIntegrationError("create approval unavailable")
        approval = ControlHubApprovalItemRead(
            id=self._next_id,
            title=item.title,
            description=item.description,
            action_type=item.action_type,
            payload_json=item.payload_json,
            status="PENDING",
            requested_by=item.requested_by,
            assigned_to=item.assigned_to,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
            decided_at=None,
            decided_by=None,
            decision_reason=None,
        )
        self.items[self._next_id] = approval
        self._next_id += 1
        return approval

    async def get_approval(self, item_id: int) -> ControlHubApprovalItemRead:
        if self.fail_get:
            raise ControlHubIntegrationError("get approval unavailable")
        return self.items[item_id]

    async def list_approvals(self, **_: object) -> list[ControlHubApprovalItemRead]:
        return list(self.items.values())

    def set_status(self, item_id: int, status: str, reason: str | None = None) -> None:
        item = self.items[item_id]
        self.items[item_id] = item.model_copy(
            update={
                "status": status,
                "decision_reason": reason,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )


class FakeProvider:
    def __init__(self, provider_name: str, *, should_fail: bool = False) -> None:
        self.provider_name = provider_name
        self.should_fail = should_fail
        self.calls: list[str] = []

    async def execute(self, work_package):
        self.calls.append(work_package.run_id)
        if self.should_fail:
            raise ProviderExecutionError(f"{self.provider_name} exploded")
        return WorkerExecutionResult(
            provider=self.provider_name,
            worker_target=work_package.worker_target,
            branch_name=work_package.branch_strategy,
            commit_shas=["deadbeef1234"],
            pr_title="Example PR",
            pr_body="Created from fake provider",
            pr_url=f"https://git.example/{work_package.repo}/pull/101",
            pr_number=101,
            execution_summary="Executed work package",
            known_risks=[],
        )


class FakeProviderRouter(PolicyBasedProviderRouter):
    def __init__(
        self,
        *,
        fallback_enabled: bool = False,
        failing_providers: set[str] | None = None,
    ) -> None:
        failing_providers = failing_providers or set()
        super().__init__(
            default_provider="codex",
            repo_overrides={},
            fallback_enabled=fallback_enabled,
            providers={
                "codex": FakeProvider("codex", should_fail="codex" in failing_providers),
                "copilot_cli": FakeProvider(
                    "copilot_cli",
                    should_fail="copilot_cli" in failing_providers,
                ),
            },
        )

    @property
    def codex_provider(self) -> FakeProvider:
        return self._providers["codex"]  # type: ignore[return-value]

    @property
    def copilot_provider(self) -> FakeProvider:
        return self._providers["copilot_cli"]  # type: ignore[return-value]


class FakePullRequestStateClient:
    def __init__(self) -> None:
        self.states: dict[str, PullRequestState] = {}

    async def get_state(self, run: OrchestrationRun) -> PullRequestState | None:
        return deepcopy(self.states.get(run.id))

    def set_state(self, run_id: str, state: PullRequestState) -> None:
        self.states[run_id] = state


class FakeRagClient:
    def __init__(self) -> None:
        self.fail_stage = False
        self.fail_promote = False
        self.fail_stale = False
        self.receipts: list[RagIngestionReceipt] = []

    async def stage_provisional(self, artifact) -> RagIngestionReceipt:
        if self.fail_stage:
            raise RagIngestionError("stage unavailable")
        receipt = RagIngestionReceipt(
            status="staged",
            artifact_id=artifact.manifest.artifact_id,
            operation="stage_provisional",
            remote_id=f"remote-{artifact.manifest.artifact_id}",
        )
        self.receipts.append(receipt)
        return receipt

    async def promote(self, artifact) -> RagIngestionReceipt:
        if self.fail_promote:
            raise RagIngestionError("promote unavailable")
        receipt = RagIngestionReceipt(
            status="promoted",
            artifact_id=artifact.manifest.artifact_id,
            operation="promote",
            remote_id=f"remote-{artifact.manifest.artifact_id}",
        )
        self.receipts.append(receipt)
        return receipt

    async def mark_stale(self, artifact, *, reason: str) -> RagIngestionReceipt:
        if self.fail_stale:
            raise RagIngestionError("stale unavailable")
        receipt = RagIngestionReceipt(
            status="stale",
            artifact_id=artifact.manifest.artifact_id,
            operation="mark_stale",
            remote_id=f"remote-{artifact.manifest.artifact_id}",
            metadata={"reason": reason},
        )
        self.receipts.append(receipt)
        return receipt


@pytest.fixture
def orchestration_dependencies():
    repository = FakeRepository()
    control_hub = FakeControlHubClient()
    pr_client = FakePullRequestStateClient()
    rag_client = FakeRagClient()
    service = OrchestrationService(
        repository=repository,
        control_hub_client=control_hub,
        provider_router=FakeProviderRouter(),
        rag_client=rag_client,
        pr_state_client=pr_client,
    )
    return {
        "repository": repository,
        "control_hub": control_hub,
        "pr_client": pr_client,
        "rag_client": rag_client,
        "service": service,
    }


@pytest.fixture
def client(orchestration_dependencies):
    app = FastAPI()
    app.include_router(router, prefix=settings.api_prefix)
    app.include_router(tool_router, prefix=settings.api_prefix)
    app.include_router(webhook_router, prefix=settings.api_prefix)
    app.dependency_overrides[get_orchestration_service] = lambda: orchestration_dependencies[
        "service"
    ]
    return TestClient(app)


def build_failed_run(run_id: str = "failed-run") -> OrchestrationRun:
    now = datetime.now(UTC)
    return OrchestrationRun(
        id=run_id,
        user_prompt="fix bug",
        plan_summary="failed plan",
        risk_summary="risk",
        control_hub_approval_id=99,
        action_type="code_change",
        worker_type=WorkerType.CODE,
        provider=ProviderName.CODEX,
        repo="agent-service",
        pr_status=PullRequestStatus.CLOSED,
        execution_status=ExecutionStatus.FAILED,
        rag_status=RagStatus.STALE,
        failure_details="boom",
        source_metadata_json={"source": "test"},
        proposal_json={
            "requested_change_summary": "fix bug",
            "repo": "agent-service",
            "worker_target": WorkerTarget.WORKER_B.value,
            "risk_level": "medium",
            "risk_summary": "risk",
            "rollback_notes": ["revert"],
            "acceptance_criteria": ["open pr"],
            "recommended_provider": "codex",
            "pr_success_conditions": ["approved"],
            "constraints": [],
        },
        created_at=now,
        updated_at=now,
    )
