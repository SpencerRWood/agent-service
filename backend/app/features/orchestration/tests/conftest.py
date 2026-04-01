from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.features.orchestration.dependencies import get_orchestration_service
from app.features.orchestration.models import (
    ExecutionStatus,
    OrchestrationRun,
    ProviderName,
    PullRequestStatus,
    RagStatus,
    WorkerType,
)
from app.features.orchestration.router import router, tool_router
from app.features.orchestration.schemas import PullRequestState, WorkerExecutionResult
from app.features.orchestration.service import OrchestrationService
from app.integrations.control_hub.client import (
    ControlHubApprovalItemCreate,
    ControlHubApprovalItemRead,
)
from app.integrations.providers.router import PolicyBasedProviderRouter


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

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[OrchestrationRun]:
        runs = list(self.items.values())
        return runs[offset : offset + limit]


class FakeControlHubClient:
    def __init__(self) -> None:
        self._next_id = 1
        self.items: dict[int, ControlHubApprovalItemRead] = {}

    async def create_approval(
        self, item: ControlHubApprovalItemCreate
    ) -> ControlHubApprovalItemRead:
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
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    async def execute(self, work_package):
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
    def __init__(self) -> None:
        super().__init__(
            default_provider="codex",
            repo_overrides={},
            providers={
                "codex": FakeProvider("codex"),
                "copilot_cli": FakeProvider("copilot_cli"),
            },
        )


class FakePullRequestStateClient:
    def __init__(self) -> None:
        self.states: dict[str, PullRequestState] = {}

    async def get_state(self, run: OrchestrationRun) -> PullRequestState | None:
        return deepcopy(self.states.get(run.id))

    def set_state(self, run_id: str, state: PullRequestState) -> None:
        self.states[run_id] = state


@pytest.fixture
def orchestration_dependencies():
    repository = FakeRepository()
    control_hub = FakeControlHubClient()
    pr_client = FakePullRequestStateClient()
    service = OrchestrationService(
        repository=repository,
        control_hub_client=control_hub,
        provider_router=FakeProviderRouter(),
        pr_state_client=pr_client,
    )
    return {
        "repository": repository,
        "control_hub": control_hub,
        "pr_client": pr_client,
        "service": service,
    }


@pytest.fixture
def client(orchestration_dependencies):
    app = FastAPI()
    app.include_router(router)
    app.include_router(tool_router)
    app.dependency_overrides[get_orchestration_service] = lambda: orchestration_dependencies["service"]
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
