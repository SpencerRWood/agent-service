from fastapi import APIRouter, Depends, HTTPException, status

from app.features.orchestration.dependencies import get_orchestration_service
from app.features.orchestration.schemas import CreateRunRequest, PullRequestEventRequest
from app.features.orchestration.service import OrchestrationService
from app.integrations.control_hub.client import (
    ControlHubClient,
    ControlHubIntegrationError,
    HttpControlHubClient,
)
from app.projections.interaction.schemas import (
    InteractionApprovalDecisionRequest,
    InteractionPullRequestEventRequest,
    InteractionRequestCreate,
    InteractionRunResponse,
)

router = APIRouter(tags=["interaction"])


def get_control_hub_client() -> ControlHubClient:
    return HttpControlHubClient.from_settings()


def _to_projection_response(run) -> InteractionRunResponse:
    if run.execution_status == "awaiting_approval":
        next_action = "Approve or reject the request, then reconcile if needed."
    elif run.execution_status == "pr_open":
        next_action = "Review the PR, then submit a pull request status update."
    elif run.execution_status == "docs_staged":
        next_action = "Merge the PR to promote provisional artifacts."
    else:
        next_action = "Inspect run status or continue the workflow as needed."

    if run.execution_status == "awaiting_approval":
        summary = "Approval is pending before execution can start."
    elif run.execution_status == "pr_open":
        summary = "Execution opened a pull request and is awaiting review."
    elif run.execution_status == "docs_staged":
        summary = "Provisional artifacts were staged and are waiting for merge promotion."
    elif run.execution_status == "completed":
        summary = "Run completed successfully."
    elif run.execution_status == "failed":
        summary = f"Run failed. {run.failure_details or ''}".strip()
    elif run.execution_status == "rejected":
        summary = f"Run was rejected. {run.failure_details or ''}".strip()
    else:
        summary = f"Run is in state '{run.execution_status.value}'."

    return InteractionRunResponse(
        run_id=run.id,
        approval_item_id=run.control_hub_approval_id,
        execution_status=run.execution_status,
        rag_status=run.rag_status,
        pr_status=run.pr_status,
        provider=run.provider,
        repo=run.repo,
        pr_url=run.pr_url,
        summary=summary,
        next_action=next_action,
    )


@router.post(
    "/requests",
    response_model=InteractionRunResponse,
    status_code=201,
    summary="Create an agent request from prompt intake",
    description=(
        "Submit prompt-based intake for the agent platform. "
        "This creates a request, an approval checkpoint if needed, and an execution run."
    ),
)
async def create_request(
    request: InteractionRequestCreate,
    service: OrchestrationService = Depends(get_orchestration_service),
) -> InteractionRunResponse:
    created = await service.create_run(
        CreateRunRequest(
            user_prompt=request.prompt,
            repo=request.repo,
            project=request.project,
            worker_target=request.worker_target,
            requested_by=request.requested_by or request.username or "chat-client",
            assigned_to=request.assigned_to,
            source_metadata={
                "source": "interaction_api",
                "conversation_id": request.conversation_id,
                "message_id": request.message_id,
                "user_id": request.user_id,
                "username": request.username,
                "labels": request.labels,
                "execution_target": request.extra.get("execution_target"),
                "extra": request.extra,
            },
        )
    )
    return _to_projection_response(created)


@router.get(
    "/requests/{run_id}",
    response_model=InteractionRunResponse,
    summary="Get request status",
    description=(
        "Read the current state of an agent request, including approval, execution, and PR status."
    ),
)
async def get_request(
    run_id: str,
    service: OrchestrationService = Depends(get_orchestration_service),
) -> InteractionRunResponse:
    run = await service.get_run(run_id)
    return _to_projection_response(run)


@router.post(
    "/requests/{run_id}/approve",
    response_model=InteractionRunResponse,
    summary="Approve a pending request",
    description="Approve the current approval checkpoint and immediately reconcile the run.",
)
async def approve_request(
    run_id: str,
    request: InteractionApprovalDecisionRequest,
    service: OrchestrationService = Depends(get_orchestration_service),
    control_hub: ControlHubClient = Depends(get_control_hub_client),
) -> InteractionRunResponse:
    run = await service.get_run(run_id)
    if run.control_hub_approval_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run does not have an approval item to approve.",
        )
    try:
        await control_hub.approve_approval(
            run.control_hub_approval_id,
            decided_by=request.decided_by,
            decision_reason=request.decision_reason,
        )
    except ControlHubIntegrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to approve Control Hub item: {exc}",
        ) from exc
    reconciled = await service.reconcile_run(run_id)
    return _to_projection_response(reconciled.run)


@router.post(
    "/requests/{run_id}/reject",
    response_model=InteractionRunResponse,
    summary="Reject a pending request",
    description="Reject the current approval checkpoint and immediately reconcile the run.",
)
async def reject_request(
    run_id: str,
    request: InteractionApprovalDecisionRequest,
    service: OrchestrationService = Depends(get_orchestration_service),
    control_hub: ControlHubClient = Depends(get_control_hub_client),
) -> InteractionRunResponse:
    run = await service.get_run(run_id)
    if run.control_hub_approval_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run does not have an approval item to reject.",
        )
    if not request.decision_reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="decision_reason is required when rejecting a request.",
        )
    try:
        await control_hub.reject_approval(
            run.control_hub_approval_id,
            decided_by=request.decided_by,
            decision_reason=request.decision_reason,
        )
    except ControlHubIntegrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to reject Control Hub item: {exc}",
        ) from exc
    reconciled = await service.reconcile_run(run_id)
    return _to_projection_response(reconciled.run)


@router.post(
    "/requests/{run_id}/pull-request-events",
    response_model=InteractionRunResponse,
    summary="Apply a pull request state change",
    description=(
        "Advance the request after pull request review changes. "
        "Useful for testing approval, merge, and stale-artifact flows from chat."
    ),
)
async def apply_pull_request_event(
    run_id: str,
    request: InteractionPullRequestEventRequest,
    service: OrchestrationService = Depends(get_orchestration_service),
) -> InteractionRunResponse:
    run = await service.apply_pull_request_event(
        run_id,
        PullRequestEventRequest(
            status=request.status,
            approved_by=request.approved_by,
            merged_at=request.merged_at,
            source=request.source,
        ),
    )
    return _to_projection_response(run)


@router.post(
    "/requests/{run_id}/reconcile",
    response_model=InteractionRunResponse,
    summary="Reconcile a request",
    description="Refresh the request from approval and PR state and advance the workflow if possible.",
)
async def reconcile_request(
    run_id: str,
    service: OrchestrationService = Depends(get_orchestration_service),
) -> InteractionRunResponse:
    reconciled = await service.reconcile_run(run_id)
    return _to_projection_response(reconciled.run)
