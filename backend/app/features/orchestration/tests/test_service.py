import asyncio
from datetime import UTC, datetime

from fastapi import HTTPException

from app.features.orchestration.models import ExecutionStatus, PullRequestStatus, RagStatus
from app.features.orchestration.schemas import (
    CreateRunRequest,
    ProjectContext,
    PullRequestEventRequest,
    PullRequestState,
    WorkerTarget,
)
from app.features.orchestration.tests.conftest import build_failed_run


def test_rejected_approval_ends_run(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    control_hub = orchestration_dependencies["control_hub"]

    run = asyncio.run(
        service.create_run(CreateRunRequest(user_prompt="Delete old feature flags", repo="agent-service"))
    )
    control_hub.set_status(run.control_hub_approval_id, "REJECTED", reason="Too risky")

    reconciled = asyncio.run(service.reconcile_run(run.id))

    assert reconciled.run.execution_status == ExecutionStatus.REJECTED
    assert reconciled.run.failure_details == "Too risky"


def test_pr_approval_triggers_docs_stage(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    control_hub = orchestration_dependencies["control_hub"]
    pr_client = orchestration_dependencies["pr_client"]

    run = asyncio.run(
        service.create_run(CreateRunRequest(user_prompt="Refactor orchestration service", repo="agent-service"))
    )
    control_hub.set_status(run.control_hub_approval_id, "APPROVED")
    asyncio.run(service.reconcile_run(run.id))
    pr_client.set_state(
        run.id,
        PullRequestState(status=PullRequestStatus.APPROVED, approved_by=["reviewer"]),
    )

    reconciled = asyncio.run(service.reconcile_run(run.id))

    assert reconciled.run.execution_status == ExecutionStatus.DOCS_STAGED
    assert reconciled.run.rag_status == RagStatus.PROVISIONAL
    assert reconciled.run.knowledge_artifact_json is not None


def test_pr_merge_promotes_rag(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    control_hub = orchestration_dependencies["control_hub"]
    pr_client = orchestration_dependencies["pr_client"]

    run = asyncio.run(
        service.create_run(CreateRunRequest(user_prompt="Refactor orchestration service", repo="agent-service"))
    )
    control_hub.set_status(run.control_hub_approval_id, "APPROVED")
    asyncio.run(service.reconcile_run(run.id))
    pr_client.set_state(run.id, PullRequestState(status=PullRequestStatus.APPROVED))
    asyncio.run(service.reconcile_run(run.id))
    pr_client.set_state(
        run.id,
        PullRequestState(status=PullRequestStatus.MERGED, merged_at=datetime.now(UTC)),
    )

    reconciled = asyncio.run(service.reconcile_run(run.id))

    assert reconciled.run.execution_status == ExecutionStatus.COMPLETED
    assert reconciled.run.rag_status == RagStatus.PROMOTED


def test_pr_changes_requested_marks_knowledge_stale(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    control_hub = orchestration_dependencies["control_hub"]

    run = asyncio.run(
        service.create_run(CreateRunRequest(user_prompt="Refactor orchestration service", repo="agent-service"))
    )
    control_hub.set_status(run.control_hub_approval_id, "APPROVED")
    asyncio.run(service.reconcile_run(run.id))
    asyncio.run(
        service.apply_pull_request_event(
            run.id,
            PullRequestEventRequest(status=PullRequestStatus.APPROVED, approved_by=["reviewer"]),
        )
    )

    updated = asyncio.run(
        service.apply_pull_request_event(
            run.id,
            PullRequestEventRequest(status=PullRequestStatus.CHANGES_REQUESTED),
        )
    )

    assert updated.rag_status == RagStatus.STALE
    assert updated.execution_status == ExecutionStatus.PR_OPEN


def test_retry_failed_run_recreates_approval(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    repository = orchestration_dependencies["repository"]

    failed_run = build_failed_run()
    asyncio.run(repository.create(failed_run))

    retried = asyncio.run(service.retry_run(failed_run.id, "Retry after fixes"))

    assert retried.execution_status == ExecutionStatus.AWAITING_APPROVAL
    assert retried.control_hub_approval_id == 1


def test_retry_non_failed_run_is_rejected(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    run = asyncio.run(service.create_run(CreateRunRequest(user_prompt="Add endpoint", repo="agent-service")))

    try:
        asyncio.run(service.retry_run(run.id))
    except HTTPException as exc:
        assert exc.status_code == 409
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("retry_run should reject non-failed runs")


def test_create_run_persists_project_and_worker_target(orchestration_dependencies):
    service = orchestration_dependencies["service"]

    run = asyncio.run(
        service.create_run(
            CreateRunRequest(
                user_prompt="Add project scoped execution",
                repo="agent-service",
                project=ProjectContext(
                    project_id="proj_123",
                    project_slug="agent-platform",
                    project_path="services/agent-platform",
                ),
                worker_target=WorkerTarget.WORKER_B,
            )
        )
    )

    assert run.proposal_json["project"]["project_slug"] == "agent-platform"
    assert run.proposal_json["worker_target"] == WorkerTarget.WORKER_B.value


def test_reconcile_builds_project_aware_branch_strategy(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    control_hub = orchestration_dependencies["control_hub"]

    run = asyncio.run(
        service.create_run(
            CreateRunRequest(
                user_prompt="Implement project aware branch naming",
                repo="agent-service",
                project=ProjectContext(project_slug="control-hub"),
            )
        )
    )
    control_hub.set_status(run.control_hub_approval_id, "APPROVED")

    reconciled = asyncio.run(service.reconcile_run(run.id))

    assert reconciled.run.work_package_json["project"]["project_slug"] == "control-hub"
    assert reconciled.run.work_package_json["worker_target"] == WorkerTarget.WORKER_B.value
    assert reconciled.run.branch.startswith("orchestration/agent-service/control-hub/worker-b/")
