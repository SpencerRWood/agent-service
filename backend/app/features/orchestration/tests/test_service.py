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
from app.features.orchestration.service import OrchestrationService
from app.features.orchestration.tests.conftest import FakeProviderRouter, build_failed_run


def test_rejected_approval_ends_run(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    control_hub = orchestration_dependencies["control_hub"]

    run = asyncio.run(
        service.create_run(
            CreateRunRequest(user_prompt="Delete old feature flags", repo="agent-service")
        )
    )
    control_hub.set_status(run.control_hub_approval_id, "REJECTED", reason="Too risky")

    reconciled = asyncio.run(service.reconcile_run(run.id))

    assert reconciled.run.execution_status == ExecutionStatus.REJECTED
    assert reconciled.run.failure_details == "Too risky"


def test_pr_approval_triggers_docs_stage(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    control_hub = orchestration_dependencies["control_hub"]
    pr_client = orchestration_dependencies["pr_client"]
    rag_client = orchestration_dependencies["rag_client"]

    run = asyncio.run(
        service.create_run(
            CreateRunRequest(user_prompt="Refactor orchestration service", repo="agent-service")
        )
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
    assert reconciled.run.knowledge_artifact_json["manifest"]["stage"] == "provisional"
    assert len(reconciled.run.knowledge_artifact_json["documents"]) == 2
    assert reconciled.run.knowledge_artifact_json["documents"][0]["path"].endswith(
        "implementation-summary.md"
    )
    assert rag_client.receipts[-1].operation == "stage_provisional"
    assert (
        reconciled.run.knowledge_artifact_json["promotion_history"][-1]["event"]
        == "rag_stage_provisional"
    )


def test_pr_merge_promotes_rag(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    control_hub = orchestration_dependencies["control_hub"]
    pr_client = orchestration_dependencies["pr_client"]
    rag_client = orchestration_dependencies["rag_client"]

    run = asyncio.run(
        service.create_run(
            CreateRunRequest(user_prompt="Refactor orchestration service", repo="agent-service")
        )
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
    assert reconciled.run.knowledge_artifact_json["manifest"]["stage"] == "promoted"
    assert reconciled.run.knowledge_artifact_json["provisional"] is False
    assert rag_client.receipts[-1].operation == "promote"
    assert reconciled.run.knowledge_artifact_json["promotion_history"][-1]["event"] == "rag_promote"


def test_pr_changes_requested_marks_knowledge_stale(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    control_hub = orchestration_dependencies["control_hub"]
    rag_client = orchestration_dependencies["rag_client"]

    run = asyncio.run(
        service.create_run(
            CreateRunRequest(user_prompt="Refactor orchestration service", repo="agent-service")
        )
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
    assert updated.knowledge_artifact_json["manifest"]["stage"] == "stale"
    assert rag_client.receipts[-1].operation == "mark_stale"
    assert updated.knowledge_artifact_json["promotion_history"][-1]["event"] == "rag_mark_stale"
    assert updated.knowledge_artifact_json["documents"][0]["metadata"]["stale"] is True


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
    run = asyncio.run(
        service.create_run(CreateRunRequest(user_prompt="Add endpoint", repo="agent-service"))
    )

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
    assert run.control_hub_approval_id == 1


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
    assert reconciled.run.knowledge_artifact_json is None


def test_reconcile_falls_back_to_secondary_provider(orchestration_dependencies):
    repository = orchestration_dependencies["repository"]
    control_hub = orchestration_dependencies["control_hub"]
    pr_client = orchestration_dependencies["pr_client"]
    service = OrchestrationService(
        repository=repository,
        control_hub_client=control_hub,
        provider_router=FakeProviderRouter(
            fallback_enabled=True,
            failing_providers={"codex"},
        ),
        rag_client=orchestration_dependencies["rag_client"],
        pr_state_client=pr_client,
    )

    run = asyncio.run(
        service.create_run(
            CreateRunRequest(user_prompt="Implement provider fallback", repo="agent-service")
        )
    )
    control_hub.set_status(run.control_hub_approval_id, "APPROVED")

    reconciled = asyncio.run(service.reconcile_run(run.id))

    assert reconciled.run.execution_status == ExecutionStatus.PR_OPEN
    assert reconciled.run.provider == "copilot_cli"
    assert reconciled.run.execution_result_json["provider"] == "copilot_cli"
    assert (
        "Primary provider 'codex' failed" in reconciled.run.execution_result_json["known_risks"][0]
    )


def test_generated_artifact_includes_project_context(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    control_hub = orchestration_dependencies["control_hub"]

    run = asyncio.run(
        service.create_run(
            CreateRunRequest(
                user_prompt="Generate project-scoped artifact",
                repo="agent-service",
                project=ProjectContext(project_slug="control-hub", project_path="apps/control-hub"),
            )
        )
    )
    control_hub.set_status(run.control_hub_approval_id, "APPROVED")
    asyncio.run(service.reconcile_run(run.id))

    updated = asyncio.run(
        service.apply_pull_request_event(
            run.id,
            PullRequestEventRequest(status=PullRequestStatus.APPROVED, approved_by=["reviewer"]),
        )
    )

    assert updated.knowledge_artifact_json["manifest"]["project"]["project_slug"] == "control-hub"
    assert "control-hub" in updated.knowledge_artifact_json["manifest"]["tags"]
    assert "Project: control-hub" in updated.knowledge_artifact_json["documents"][0]["content"]


def test_create_run_uses_agent_registry_defaults(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    control_hub = orchestration_dependencies["control_hub"]

    run = asyncio.run(service.create_run(CreateRunRequest(user_prompt="Use configured agents")))
    approval = control_hub.items[run.control_hub_approval_id]

    assert approval.requested_by == "agent-a"
    assert approval.assigned_to == "worker-b"
    assert run.proposal_json["worker_target"] == WorkerTarget.WORKER_B.value


def test_reconcile_without_fallback_marks_run_failed(orchestration_dependencies):
    repository = orchestration_dependencies["repository"]
    control_hub = orchestration_dependencies["control_hub"]
    pr_client = orchestration_dependencies["pr_client"]
    service = OrchestrationService(
        repository=repository,
        control_hub_client=control_hub,
        provider_router=FakeProviderRouter(failing_providers={"codex"}),
        rag_client=orchestration_dependencies["rag_client"],
        pr_state_client=pr_client,
    )

    run = asyncio.run(
        service.create_run(
            CreateRunRequest(user_prompt="Implement provider fallback", repo="agent-service")
        )
    )
    control_hub.set_status(run.control_hub_approval_id, "APPROVED")

    reconciled = asyncio.run(service.reconcile_run(run.id))

    assert reconciled.run.execution_status == ExecutionStatus.FAILED
    assert "Worker execution failed" in reconciled.run.failure_details


def test_create_run_surfaces_control_hub_error(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    orchestration_dependencies["control_hub"].fail_create = True

    try:
        asyncio.run(
            service.create_run(CreateRunRequest(user_prompt="Add endpoint", repo="agent-service"))
        )
    except HTTPException as exc:
        assert exc.status_code == 502
        assert "Failed to create Control Hub approval" in exc.detail
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("create_run should surface Control Hub failures")


def test_reconcile_surfaces_control_hub_get_error(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    control_hub = orchestration_dependencies["control_hub"]

    run = asyncio.run(
        service.create_run(CreateRunRequest(user_prompt="Add endpoint", repo="agent-service"))
    )
    control_hub.fail_get = True

    try:
        asyncio.run(service.reconcile_run(run.id))
    except HTTPException as exc:
        assert exc.status_code == 502
        assert "Failed to fetch Control Hub approval" in exc.detail
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("reconcile_run should surface Control Hub failures")


def test_pr_approval_marks_rag_failed_when_stage_ingest_fails(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    control_hub = orchestration_dependencies["control_hub"]
    pr_client = orchestration_dependencies["pr_client"]
    orchestration_dependencies["rag_client"].fail_stage = True

    run = asyncio.run(
        service.create_run(
            CreateRunRequest(user_prompt="Refactor orchestration service", repo="agent-service")
        )
    )
    control_hub.set_status(run.control_hub_approval_id, "APPROVED")
    asyncio.run(service.reconcile_run(run.id))
    pr_client.set_state(run.id, PullRequestState(status=PullRequestStatus.APPROVED))

    reconciled = asyncio.run(service.reconcile_run(run.id))

    assert reconciled.run.execution_status == ExecutionStatus.PR_APPROVED
    assert reconciled.run.rag_status == RagStatus.FAILED
    assert "RAG provisional ingestion failed" in reconciled.run.failure_details
    assert (
        reconciled.run.knowledge_artifact_json["promotion_history"][-1]["event"]
        == "rag_stage_provisional"
    )
    assert reconciled.run.knowledge_artifact_json["promotion_history"][-1]["status"] == "failed"


def test_pr_merge_marks_rag_failed_when_promotion_fails(orchestration_dependencies):
    service = orchestration_dependencies["service"]
    control_hub = orchestration_dependencies["control_hub"]
    pr_client = orchestration_dependencies["pr_client"]
    orchestration_dependencies["rag_client"].fail_promote = True

    run = asyncio.run(
        service.create_run(
            CreateRunRequest(user_prompt="Refactor orchestration service", repo="agent-service")
        )
    )
    control_hub.set_status(run.control_hub_approval_id, "APPROVED")
    asyncio.run(service.reconcile_run(run.id))
    asyncio.run(
        service.apply_pull_request_event(
            run.id,
            PullRequestEventRequest(status=PullRequestStatus.APPROVED, approved_by=["reviewer"]),
        )
    )
    pr_client.set_state(run.id, PullRequestState(status=PullRequestStatus.MERGED))

    reconciled = asyncio.run(service.reconcile_run(run.id))

    assert reconciled.run.execution_status == ExecutionStatus.MERGED
    assert reconciled.run.rag_status == RagStatus.FAILED
    assert "RAG promotion failed" in reconciled.run.failure_details
    assert reconciled.run.knowledge_artifact_json["promotion_history"][-1]["event"] == "rag_promote"
    assert reconciled.run.knowledge_artifact_json["promotion_history"][-1]["status"] == "failed"
