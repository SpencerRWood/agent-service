from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Protocol
from uuid import uuid4

from fastapi import HTTPException, status

from app.core.logging import get_logger
from app.core.settings import settings
from app.features.orchestration.models import (
    ExecutionStatus,
    OrchestrationRun,
    ProviderName,
    PullRequestStatus,
    RagStatus,
    WorkerType,
)
from app.features.orchestration.platform_bridge import NullPlatformRecorder, PlatformRecorder
from app.features.orchestration.schemas import (
    ActionType,
    ApprovedWorkPackage,
    ArtifactFile,
    ArtifactManifest,
    ArtifactStage,
    ChatToolCreateRunRequest,
    ChatToolRunResponse,
    ChatToolStatusResponse,
    CreateRunRequest,
    ExecutionProposal,
    KnowledgeCaptureArtifact,
    ProjectContext,
    PullRequestEventRequest,
    PullRequestState,
    ReconcileResponse,
    RiskLevel,
    RunListResponse,
    RunRead,
    WorkerExecutionResult,
    WorkerTarget,
)
from app.integrations.control_hub.client import (
    ApprovalStatus,
    ControlHubApprovalItemCreate,
    ControlHubClient,
    ControlHubIntegrationError,
)
from app.integrations.providers.router import PolicyBasedProviderRouter, ProviderRoutingError
from app.integrations.rag.client import (
    NoOpRagIngestionClient,
    RagIngestionClient,
    RagIngestionReceipt,
)
from app.platform.execution_targets.dispatcher import (
    NullRemoteExecutionDispatcher,
    RemoteExecutionDispatcher,
)
from app.platform.tools.runtime import (
    ToolExecutionError,
    ToolRuntime,
    parse_rag_receipt,
    parse_worker_execution_result,
)

logger = get_logger(__name__)


class PullRequestStateClient(Protocol):
    async def get_state(self, run: OrchestrationRun) -> PullRequestState | None: ...

    async def get_pull_request_state(
        self,
        *,
        repo: str,
        pr_number: int,
    ) -> PullRequestState | None: ...


class NullPullRequestStateClient:
    async def get_state(self, run: OrchestrationRun) -> PullRequestState | None:
        return None

    async def get_pull_request_state(
        self,
        *,
        repo: str,
        pr_number: int,
    ) -> PullRequestState | None:
        del repo, pr_number
        return None


class OrchestrationRepository(Protocol):
    async def create(self, run: OrchestrationRun) -> OrchestrationRun: ...

    async def update(self, run: OrchestrationRun) -> OrchestrationRun: ...

    async def get(self, run_id: str) -> OrchestrationRun | None: ...

    async def get_by_repo_and_pr_number(
        self,
        *,
        repo: str,
        pr_number: int,
    ) -> OrchestrationRun | None: ...

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[OrchestrationRun]: ...


@dataclass
class AgentAResult:
    proposal: ExecutionProposal
    plan_summary: str
    risk_summary: str


class PlannerRiskAgent:
    def build_plan(self, request: CreateRunRequest) -> AgentAResult:
        repo = request.repo or settings.orchestration_default_repo
        worker_b_profile = settings.agent_registry.get_agent("worker_b")
        configured_target = request.worker_target or (
            worker_b_profile.worker_target
            if worker_b_profile is not None and worker_b_profile.worker_target is not None
            else WorkerTarget(settings.orchestration_default_worker_target)
        )
        worker_target = self._resolve_worker_target(
            configured_target,
            request.user_prompt,
        )
        lowered = request.user_prompt.lower()
        risk_level = (
            RiskLevel.HIGH
            if any(token in lowered for token in ["delete", "drop", "migrate", "auth", "billing"])
            else RiskLevel.MEDIUM
        )
        recommended_provider = (
            ProviderName.COPILOT_CLI if "copilot" in lowered else ProviderName.CODEX
        )

        proposal = ExecutionProposal(
            requested_change_summary=request.user_prompt.strip(),
            repo=repo,
            project=request.project,
            worker_target=worker_target,
            risk_level=risk_level,
            risk_summary=(
                "Planner flagged this request for review before execution because "
                "Worker B opens a pull request against a live repository."
            ),
            rollback_notes=[
                "Revert the generated branch or pull request if the implementation is rejected.",
                "Do not promote knowledge artifacts unless the pull request lifecycle reaches merge.",
            ],
            acceptance_criteria=[
                "A pull request is opened for the requested repository.",
                "The pull request contains a clear summary of the requested change.",
                "Execution metadata is persisted on the orchestration run.",
            ],
            recommended_provider=recommended_provider,
            pr_success_conditions=[
                "Pull request opens successfully.",
                "Pull request enters approved state before docs capture runs.",
            ],
            constraints=[
                "Code-task only v1 workflow.",
                "Approval must be granted in Control Hub before execution starts.",
            ],
        )
        return AgentAResult(
            proposal=proposal,
            plan_summary=f"Plan generated for repo '{repo}' from the user prompt.",
            risk_summary=proposal.risk_summary,
        )

    def _resolve_worker_target(
        self,
        worker_target: WorkerTarget,
        user_prompt: str,
    ) -> WorkerTarget:
        if worker_target != WorkerTarget.AUTO:
            return worker_target

        lowered = user_prompt.lower()
        artifact_keywords = {
            "artifact",
            "artifacts",
            "docs",
            "documentation",
            "knowledge",
            "rag",
            "ingestion",
            "operational notes",
            "implementation summary",
        }
        if any(keyword in lowered for keyword in artifact_keywords):
            return WorkerTarget.AGENT_C

        return WorkerTarget.WORKER_B


class KnowledgeCaptureAgent:
    def capture(self, run: OrchestrationRun) -> KnowledgeCaptureArtifact:
        proposal = ExecutionProposal.model_validate(run.proposal_json)
        artifact_id = f"artifact-{uuid4().hex[:12]}"
        generated_at = datetime.now(UTC)
        source_pr_url = run.pr_url or ""
        tags = [
            run.repo,
            run.provider.value,
            proposal.worker_target.value,
            proposal.project.project_slug
            if proposal.project and proposal.project.project_slug
            else "default",
        ]
        implementation_doc = ArtifactFile.from_content(
            path=f"artifacts/{run.id}/implementation-summary.md",
            media_type="text/markdown",
            title="Implementation Summary",
            content="\n".join(
                [
                    f"# Implementation Summary for {run.repo}",
                    "",
                    f"Run ID: {run.id}",
                    f"Provider: {run.provider.value}",
                    f"Worker Target: {proposal.worker_target.value}",
                    f"Project: {self._project_label(proposal.project)}",
                    f"PR: {source_pr_url or 'pending'}",
                    "",
                    "## Requested Change",
                    run.user_prompt,
                    "",
                    "## Execution Summary",
                    (run.execution_result_json or {}).get(
                        "execution_summary", "Execution summary not available."
                    ),
                ]
            ),
            metadata={"kind": "implementation_summary", "provisional": True},
        )
        operations_doc = ArtifactFile.from_content(
            path=f"artifacts/{run.id}/operational-notes.md",
            media_type="text/markdown",
            title="Operational Notes",
            content="\n".join(
                [
                    f"# Operational Notes for {run.repo}",
                    "",
                    "## Review Gates",
                    "- Knowledge is provisional until the PR is merged.",
                    "- If PR approval is dismissed or changes are requested, mark the artifact stale.",
                    "",
                    "## Rollback Notes",
                    *[f"- {note}" for note in proposal.rollback_notes],
                    "",
                    "## Acceptance Criteria",
                    *[f"- {criterion}" for criterion in proposal.acceptance_criteria],
                ]
            ),
            metadata={"kind": "operational_notes", "provisional": True},
        )
        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            repo=run.repo,
            project=proposal.project,
            provider=run.provider,
            worker_target=proposal.worker_target,
            stage=ArtifactStage.PROVISIONAL,
            generated_at=generated_at,
            source_run_id=run.id,
            source_pr_url=source_pr_url,
            source_pr_number=run.pr_number,
            tags=[tag for tag in tags if tag],
        )
        return KnowledgeCaptureArtifact(
            implementation_summary=self._implementation_summary(run),
            manifest=manifest,
            operational_notes=[
                "Knowledge is provisional until the PR is merged.",
                "If PR approval is dismissed or changes are requested, mark the artifact stale.",
            ],
            decision_log=[
                f"Provider selected: {run.provider.value}",
                f"Control Hub approval: {run.control_hub_approval_id}",
                f"Artifact generated: {artifact_id}",
            ],
            knowledge_chunks=[
                run.plan_summary,
                run.risk_summary,
                f"PR URL: {run.pr_url}",
                implementation_doc.content,
            ],
            documents=[implementation_doc, operations_doc],
            promotion_history=[
                {
                    "event": "generated",
                    "stage": ArtifactStage.PROVISIONAL.value,
                    "timestamp": generated_at.isoformat(),
                }
            ],
            source_pr_url=run.pr_url or "",
            provisional=True,
        )

    def promote(self, artifact: KnowledgeCaptureArtifact) -> KnowledgeCaptureArtifact:
        promoted_at = datetime.now(UTC)
        promoted_manifest = artifact.manifest.model_copy(
            update={"stage": ArtifactStage.PROMOTED, "generated_at": promoted_at}
        )
        promoted_documents = [
            document.model_copy(
                update={
                    "metadata": {
                        **document.metadata,
                        "provisional": False,
                        "promoted_at": promoted_at.isoformat(),
                    }
                }
            )
            for document in artifact.documents
        ]
        return artifact.model_copy(
            update={
                "manifest": promoted_manifest,
                "documents": promoted_documents,
                "promotion_history": [
                    *artifact.promotion_history,
                    {
                        "event": "promoted",
                        "stage": ArtifactStage.PROMOTED.value,
                        "timestamp": promoted_at.isoformat(),
                    },
                ],
                "provisional": False,
            }
        )

    def mark_stale(
        self,
        artifact: KnowledgeCaptureArtifact,
        *,
        reason: str,
        status: PullRequestStatus,
    ) -> KnowledgeCaptureArtifact:
        stale_at = datetime.now(UTC)
        stale_manifest = artifact.manifest.model_copy(
            update={"stage": ArtifactStage.STALE, "generated_at": stale_at}
        )
        stale_documents = [
            document.model_copy(
                update={
                    "metadata": {
                        **document.metadata,
                        "stale": True,
                        "stale_reason": reason,
                        "pull_request_status": status.value,
                        "updated_at": stale_at.isoformat(),
                    }
                }
            )
            for document in artifact.documents
        ]
        return artifact.model_copy(
            update={
                "manifest": stale_manifest,
                "documents": stale_documents,
                "promotion_history": [
                    *artifact.promotion_history,
                    {
                        "event": "stale",
                        "stage": ArtifactStage.STALE.value,
                        "reason": reason,
                        "timestamp": stale_at.isoformat(),
                    },
                ],
            }
        )

    def _project_label(self, project: ProjectContext | None) -> str:
        if project is None:
            return "default"

        return project.project_slug or project.project_id or project.project_path or "default"

    def _implementation_summary(self, run: OrchestrationRun) -> str:
        if run.pr_number:
            return f"PR {run.pr_number} for repo '{run.repo}' is approved and ready for merge promotion."
        return (
            f"Artifact package for repo '{run.repo}' was generated directly by Agent C "
            "and is ready for downstream ingestion or review."
        )


class OrchestrationService:
    def __init__(
        self,
        *,
        repository: OrchestrationRepository,
        control_hub_client: ControlHubClient,
        provider_router: PolicyBasedProviderRouter,
        rag_client: RagIngestionClient | None = None,
        pr_state_client: PullRequestStateClient | None = None,
        planner_agent: PlannerRiskAgent | None = None,
        knowledge_agent: KnowledgeCaptureAgent | None = None,
        platform_recorder: PlatformRecorder | None = None,
        tool_runtime: ToolRuntime | None = None,
        remote_dispatcher: RemoteExecutionDispatcher | NullRemoteExecutionDispatcher | None = None,
    ) -> None:
        self._repository = repository
        self._control_hub = control_hub_client
        self._provider_router = provider_router
        self._rag_client = rag_client or NoOpRagIngestionClient()
        self._pr_state_client = pr_state_client or NullPullRequestStateClient()
        self._planner_agent = planner_agent or PlannerRiskAgent()
        self._knowledge_agent = knowledge_agent or KnowledgeCaptureAgent()
        self._platform_recorder = platform_recorder or NullPlatformRecorder()
        self._tool_runtime = tool_runtime or ToolRuntime.from_dependencies(
            provider_router=self._provider_router,
            rag_client=self._rag_client,
            pr_state_reader=self._pr_state_client,
            remote_dispatcher=remote_dispatcher or NullRemoteExecutionDispatcher(),
        )

    async def create_run(self, request: CreateRunRequest) -> RunRead:
        logger.info(
            "Creating orchestration run",
            extra={
                "event": "orchestration_run_create_started",
                "repo": request.repo or settings.orchestration_default_repo,
                "requested_by": request.requested_by or self._default_requested_by(),
                "worker_target": (
                    request.worker_target.value if request.worker_target is not None else "auto"
                ),
            },
        )
        agent_result = self._planner_agent.build_plan(request)
        try:
            provider_name = self._provider_router.choose_provider_name(agent_result.proposal)
        except ProviderRoutingError as exc:
            logger.warning(
                "Failed to select orchestration provider",
                extra={
                    "event": "orchestration_provider_selection_failed",
                    "repo": agent_result.proposal.repo,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Unable to route orchestration provider: {exc}",
            ) from exc

        try:
            approval = await self._control_hub.create_approval(
                ControlHubApprovalItemCreate(
                    title=f"Approve code task for {agent_result.proposal.repo}",
                    description=agent_result.plan_summary,
                    action_type=ActionType.CODE_CHANGE.value,
                    payload_json={
                        "user_prompt": request.user_prompt,
                        "execution_proposal": agent_result.proposal.model_dump(mode="json"),
                        "worker_type": WorkerType.CODE.value,
                        "worker_target": agent_result.proposal.worker_target.value,
                        "provider": provider_name.value,
                    },
                    requested_by=request.requested_by or self._default_requested_by(),
                    assigned_to=request.assigned_to or self._default_assigned_to(),
                )
            )
        except ControlHubIntegrationError as exc:
            logger.warning(
                "Failed to create Control Hub approval",
                extra={
                    "event": "orchestration_approval_create_failed",
                    "repo": agent_result.proposal.repo,
                    "provider": provider_name.value,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to create Control Hub approval: {exc}",
            ) from exc

        run = OrchestrationRun(
            user_prompt=request.user_prompt,
            plan_summary=agent_result.plan_summary,
            risk_summary=agent_result.risk_summary,
            control_hub_approval_id=approval.id,
            action_type=ActionType.CODE_CHANGE.value,
            worker_type=WorkerType.CODE,
            provider=provider_name,
            repo=agent_result.proposal.repo,
            pr_status=PullRequestStatus.NONE,
            execution_status=ExecutionStatus.AWAITING_APPROVAL,
            rag_status=RagStatus.NOT_STARTED,
            source_metadata_json=request.source_metadata,
            proposal_json=agent_result.proposal.model_dump(mode="json"),
        )
        created = await self._repository.create(run)
        await self._platform_recorder.record_run_created(
            created,
            requested_by=request.requested_by or self._default_requested_by(),
            assigned_to=request.assigned_to or self._default_assigned_to(),
        )
        created = await self._repository.update(created)
        logger.info(
            "Orchestration run created",
            extra={
                "event": "orchestration_run_created",
                "run_id": created.id,
                "repo": created.repo,
                "provider": created.provider.value,
                "execution_status": created.execution_status.value,
                "approval_id": created.control_hub_approval_id,
            },
        )
        return RunRead.model_validate(created)

    async def create_run_from_chat_tool(
        self, request: ChatToolCreateRunRequest
    ) -> ChatToolRunResponse:
        source_metadata = {
            "source": "control_hub_chat_tool",
            "conversation_id": request.context.conversation_id,
            "message_id": request.context.message_id,
            "user_id": request.context.user_id,
            "username": request.context.username,
            "labels": request.context.labels,
            "project": (
                request.context.project.model_dump(mode="json")
                if request.context.project is not None
                else None
            ),
            "worker_target": (
                request.context.worker_target.value
                if request.context.worker_target is not None
                else None
            ),
            "extra": request.context.extra,
        }
        run = await self.create_run(
            CreateRunRequest(
                user_prompt=request.prompt,
                repo=request.context.repo,
                project=request.context.project,
                worker_target=request.context.worker_target,
                requested_by=request.context.requested_by,
                assigned_to=request.context.assigned_to,
                source_metadata=source_metadata,
            )
        )
        return ChatToolRunResponse(
            run_id=run.id,
            approval_item_id=run.control_hub_approval_id,
            execution_status=run.execution_status,
            rag_status=run.rag_status,
            provider=run.provider,
            repo=run.repo,
            message=(
                f"Created orchestration run {run.id} for repo '{run.repo}'. "
                "A Control Hub approval item is now pending review."
            ),
            next_action="Wait for Control Hub approval, then reconcile the run.",
        )

    async def get_chat_tool_status(self, run_id: str) -> ChatToolStatusResponse:
        run = await self._require_run(run_id)
        return ChatToolStatusResponse(
            run_id=run.id,
            approval_item_id=run.control_hub_approval_id,
            execution_status=run.execution_status,
            rag_status=run.rag_status,
            pr_status=run.pr_status,
            pr_url=run.pr_url,
            repo=run.repo,
            summary=self._build_run_summary(run),
        )

    async def list_runs(self, *, limit: int = 50, offset: int = 0) -> RunListResponse:
        runs = await self._repository.list(limit=limit, offset=offset)
        return RunListResponse(items=[RunRead.model_validate(run) for run in runs])

    async def get_run(self, run_id: str) -> RunRead:
        run = await self._require_run(run_id)
        return RunRead.model_validate(run)

    async def retry_run(self, run_id: str, reason: str | None = None) -> RunRead:
        run = await self._require_run(run_id)
        if run.execution_status not in {ExecutionStatus.FAILED, ExecutionStatus.REJECTED}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only failed or rejected runs can be retried.",
            )

        try:
            approval = await self._control_hub.create_approval(
                ControlHubApprovalItemCreate(
                    title=f"Retry code task for {run.repo}",
                    description=reason or run.plan_summary,
                    action_type=run.action_type,
                    payload_json={
                        "retry_of_run_id": run.id,
                        "execution_proposal": run.proposal_json,
                        "worker_type": run.worker_type.value,
                        "worker_target": run.proposal_json.get("worker_target"),
                        "provider": run.provider.value,
                    },
                    requested_by=self._default_requested_by(),
                    assigned_to=self._default_assigned_to(),
                )
            )
        except ControlHubIntegrationError as exc:
            logger.warning(
                "Failed to create retry approval",
                extra={
                    "event": "orchestration_retry_approval_failed",
                    "run_id": run.id,
                    "repo": run.repo,
                    "provider": run.provider.value,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to create Control Hub approval: {exc}",
            ) from exc

        run.control_hub_approval_id = approval.id
        run.execution_status = ExecutionStatus.AWAITING_APPROVAL
        run.failure_details = None
        run.pr_status = PullRequestStatus.NONE
        run.rag_status = RagStatus.NOT_STARTED
        run.branch = None
        run.pr_url = None
        run.pr_number = None
        run.work_package_json = None
        run.execution_result_json = None
        run.knowledge_artifact_json = None
        updated = await self._repository.update(run)
        await self._platform_recorder.record_retry_requested(updated, reason=reason)
        updated = await self._repository.update(updated)
        logger.info(
            "Orchestration run reset for retry",
            extra={
                "event": "orchestration_run_retried",
                "run_id": updated.id,
                "repo": updated.repo,
                "provider": updated.provider.value,
                "execution_status": updated.execution_status.value,
                "approval_id": updated.control_hub_approval_id,
            },
        )
        return RunRead.model_validate(updated)

    async def reconcile_run(self, run_id: str) -> ReconcileResponse:
        run = await self._require_run(run_id)
        changed = False
        logger.info(
            "Reconciling orchestration run",
            extra={
                "event": "orchestration_run_reconcile_started",
                "run_id": run.id,
                "repo": run.repo,
                "execution_status": run.execution_status.value,
                "pr_status": run.pr_status.value,
                "rag_status": run.rag_status.value,
            },
        )

        if run.control_hub_approval_id is not None:
            try:
                approval = await self._control_hub.get_approval(run.control_hub_approval_id)
            except ControlHubIntegrationError as exc:
                logger.warning(
                    "Failed to fetch Control Hub approval during reconciliation",
                    extra={
                        "event": "orchestration_reconcile_approval_fetch_failed",
                        "run_id": run.id,
                        "approval_id": run.control_hub_approval_id,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed to fetch Control Hub approval: {exc}",
                ) from exc
            if (
                approval.status == ApprovalStatus.REJECTED
                and run.execution_status != ExecutionStatus.REJECTED
            ):
                run.execution_status = ExecutionStatus.REJECTED
                run.failure_details = approval.decision_reason or "Control Hub approval rejected."
                run.rag_status = (
                    RagStatus.STALE if run.knowledge_artifact_json else RagStatus.NOT_STARTED
                )
                await self._platform_recorder.record_approval_resolved(
                    run,
                    decision="rejected",
                    reason=run.failure_details,
                    source="control_hub",
                )
                changed = True
            elif (
                approval.status == ApprovalStatus.APPROVED
                and run.execution_status == ExecutionStatus.AWAITING_APPROVAL
            ):
                await self._platform_recorder.record_approval_resolved(
                    run,
                    decision="approved",
                    reason=approval.decision_reason,
                    source="control_hub",
                )
                await self._dispatch_target(run)
                changed = True

        pr_state = await self._pr_state_client.get_state(run)
        if pr_state is not None:
            changed = await self._apply_pull_request_state(run, pr_state) or changed
            await self._platform_recorder.record_pull_request_event(run, pr_state=pr_state)

        if changed:
            run = await self._repository.update(run)

        logger.info(
            "Orchestration reconciliation completed",
            extra={
                "event": "orchestration_run_reconcile_completed",
                "run_id": run.id,
                "repo": run.repo,
                "changed": changed,
                "execution_status": run.execution_status.value,
                "pr_status": run.pr_status.value,
                "rag_status": run.rag_status.value,
            },
        )
        return ReconcileResponse(run=RunRead.model_validate(run), changed=changed)

    async def apply_pull_request_event(
        self, run_id: str, event: PullRequestEventRequest
    ) -> RunRead:
        run = await self._require_run(run_id)
        pr_state = PullRequestState(
            status=event.status,
            approved_by=event.approved_by,
            merged_at=event.merged_at,
            source=event.source,
        )
        logger.info(
            "Applying pull request event to run",
            extra={
                "event": "orchestration_pr_event_received",
                "run_id": run.id,
                "repo": run.repo,
                "pr_status": event.status.value,
                "source": event.source,
            },
        )
        changed = await self._apply_pull_request_state(
            run,
            pr_state,
        )
        await self._platform_recorder.record_pull_request_event(run, pr_state=pr_state)
        if changed:
            run = await self._repository.update(run)
        return RunRead.model_validate(run)

    async def apply_pull_request_event_by_number(
        self,
        *,
        repo: str,
        pr_number: int,
        event: PullRequestEventRequest,
    ) -> RunRead | None:
        run = await self._repository.get_by_repo_and_pr_number(repo=repo, pr_number=pr_number)
        if run is None:
            logger.info(
                "Pull request event did not match an orchestration run",
                extra={
                    "event": "orchestration_pr_event_unmatched",
                    "repo": repo,
                    "pr_number": pr_number,
                    "pr_status": event.status.value,
                },
            )
            return None

        logger.info(
            "Applying pull request event by number",
            extra={
                "event": "orchestration_pr_event_matched",
                "run_id": run.id,
                "repo": repo,
                "pr_number": pr_number,
                "pr_status": event.status.value,
                "source": event.source,
            },
        )
        changed = await self._apply_pull_request_state(
            run,
            PullRequestState(
                status=event.status,
                approved_by=event.approved_by,
                merged_at=event.merged_at,
                source=event.source,
            ),
        )
        await self._platform_recorder.record_pull_request_event(
            run,
            pr_state=PullRequestState(
                status=event.status,
                approved_by=event.approved_by,
                merged_at=event.merged_at,
                source=event.source,
            ),
        )
        if changed:
            run = await self._repository.update(run)
        return RunRead.model_validate(run)

    async def _dispatch_target(self, run: OrchestrationRun) -> None:
        run.execution_status = ExecutionStatus.APPROVED
        proposal = ExecutionProposal.model_validate(run.proposal_json)
        logger.info(
            "Dispatching orchestration run",
            extra={
                "event": "orchestration_dispatch_started",
                "run_id": run.id,
                "repo": run.repo,
                "provider": run.provider.value,
                "worker_target": proposal.worker_target.value,
            },
        )
        if proposal.worker_target == WorkerTarget.AGENT_C:
            await self._dispatch_agent_c(run, proposal)
            return

        await self._dispatch_worker_b(run, proposal)

    async def _dispatch_worker_b(
        self,
        run: OrchestrationRun,
        proposal: ExecutionProposal,
    ) -> None:
        primary_provider_name = run.provider
        work_package = self._build_work_package(run, proposal, primary_provider_name)
        run.work_package_json = work_package.model_dump(mode="json")
        run.execution_status = ExecutionStatus.EXECUTING
        await self._platform_recorder.record_dispatch_started(
            run,
            executor_name=primary_provider_name.value,
            work_package=work_package,
        )
        logger.info(
            "Executing Worker B run",
            extra={
                "event": "orchestration_worker_b_execution_started",
                "run_id": run.id,
                "repo": run.repo,
                "provider": primary_provider_name.value,
                "worker_target": proposal.worker_target.value,
            },
        )

        try:
            result_payload = await self._tool_runtime.execute(
                "agent.execute_coding_task",
                {"work_package": work_package.model_dump(mode="json")},
            )
            result = parse_worker_execution_result(result_payload)
        except ToolExecutionError as exc:
            run.execution_status = ExecutionStatus.FAILED
            run.failure_details = f"Worker execution failed: {exc}"
            await self._platform_recorder.record_execution_failure(
                run,
                detail=run.failure_details,
            )
            logger.warning(
                "Worker B execution failed",
                extra={
                    "event": "orchestration_worker_b_execution_failed",
                    "run_id": run.id,
                    "repo": run.repo,
                    "provider": primary_provider_name.value,
                },
            )
            return
        except Exception as exc:  # pragma: no cover - defensive guard
            run.execution_status = ExecutionStatus.FAILED
            run.failure_details = f"Worker execution failed: {exc}"
            await self._platform_recorder.record_execution_failure(
                run,
                detail=run.failure_details,
            )
            logger.exception(
                "Unexpected Worker B execution failure",
                extra={
                    "event": "orchestration_worker_b_execution_exception",
                    "run_id": run.id,
                    "repo": run.repo,
                    "provider": primary_provider_name.value,
                },
            )
            return

        run.failure_details = None
        self._apply_worker_result(run, result)
        await self._platform_recorder.record_execution_result(run)

    async def _dispatch_agent_c(
        self,
        run: OrchestrationRun,
        proposal: ExecutionProposal,
    ) -> None:
        work_package = self._build_work_package(run, proposal, run.provider)
        run.work_package_json = work_package.model_dump(mode="json")
        run.execution_status = ExecutionStatus.EXECUTING
        await self._platform_recorder.record_dispatch_started(
            run,
            executor_name=proposal.worker_target.value,
            work_package=work_package,
        )
        logger.info(
            "Executing Agent C run",
            extra={
                "event": "orchestration_agent_c_execution_started",
                "run_id": run.id,
                "repo": run.repo,
                "provider": run.provider.value,
                "worker_target": proposal.worker_target.value,
            },
        )

        artifact = self._knowledge_agent.capture(run)
        run.execution_result_json = {
            "worker_target": proposal.worker_target.value,
            "execution_summary": "Agent C generated a knowledge artifact package directly.",
            "generated_documents": [document.path for document in artifact.documents],
            "artifact_id": artifact.manifest.artifact_id,
        }
        try:
            receipt_payload = await self._tool_runtime.execute(
                "rag.stage_provisional_artifact",
                {"artifact": artifact.model_dump(mode="json")},
            )
            receipt = parse_rag_receipt(receipt_payload)
        except ToolExecutionError as exc:
            run.knowledge_artifact_json = self._append_rag_receipt(
                artifact,
                operation="stage_provisional",
                status="failed",
                metadata={"error": str(exc)},
            ).model_dump(mode="json")
            run.rag_status = RagStatus.FAILED
            run.execution_status = ExecutionStatus.FAILED
            run.failure_details = f"Agent C ingestion failed: {exc}"
            await self._platform_recorder.record_execution_failure(
                run,
                detail=run.failure_details,
            )
            failed_artifact = KnowledgeCaptureArtifact.model_validate(run.knowledge_artifact_json)
            await self._platform_recorder.record_artifact_state(
                run,
                artifact=failed_artifact,
                status="failed",
            )
            logger.warning(
                "Agent C provisional ingestion failed",
                extra={
                    "event": "orchestration_agent_c_ingestion_failed",
                    "run_id": run.id,
                    "repo": run.repo,
                    "artifact_id": artifact.manifest.artifact_id,
                },
            )
            return

        artifact = self._record_rag_receipt(artifact, receipt)
        run.knowledge_artifact_json = artifact.model_dump(mode="json")
        run.rag_status = RagStatus.PROVISIONAL
        run.execution_status = ExecutionStatus.DOCS_STAGED
        run.failure_details = None
        await self._platform_recorder.record_execution_result(run)
        await self._platform_recorder.record_artifact_state(
            run,
            artifact=artifact,
            status="provisional",
        )
        logger.info(
            "Agent C provisional artifact staged",
            extra={
                "event": "orchestration_agent_c_ingestion_completed",
                "run_id": run.id,
                "repo": run.repo,
                "artifact_id": artifact.manifest.artifact_id,
                "rag_status": run.rag_status.value,
            },
        )

    def _apply_worker_result(self, run: OrchestrationRun, result: WorkerExecutionResult) -> None:
        run.provider = ProviderName(result.provider)
        run.branch = result.branch_name
        run.pr_url = result.pr_url
        run.pr_number = result.pr_number
        run.pr_status = PullRequestStatus.OPEN
        run.execution_status = ExecutionStatus.PR_OPEN
        run.execution_result_json = result.model_dump(mode="json")
        logger.info(
            "Worker execution opened pull request",
            extra={
                "event": "orchestration_worker_result_applied",
                "run_id": run.id,
                "repo": run.repo,
                "provider": run.provider.value,
                "pr_number": run.pr_number,
                "execution_status": run.execution_status.value,
            },
        )

    def _build_work_package(
        self,
        run: OrchestrationRun,
        proposal: ExecutionProposal,
        provider_name: ProviderName,
    ) -> ApprovedWorkPackage:
        return ApprovedWorkPackage(
            run_id=run.id,
            approval_id=run.control_hub_approval_id or 0,
            provider=provider_name,
            repo=run.repo,
            project=proposal.project,
            worker_target=proposal.worker_target,
            branch_strategy=self._build_branch_strategy(
                repo=run.repo,
                project=proposal.project,
                worker_target=proposal.worker_target,
                run_id=run.id,
            ),
            instructions=proposal.requested_change_summary,
            constraints=proposal.constraints,
            acceptance_criteria=proposal.acceptance_criteria,
            source_metadata=run.source_metadata_json or {},
        )

    async def _apply_pull_request_state(
        self, run: OrchestrationRun, pr_state: PullRequestState
    ) -> bool:
        changed = False
        previous_pr_status = run.pr_status
        previous_execution_status = run.execution_status
        previous_rag_status = run.rag_status
        if pr_state.status != run.pr_status:
            run.pr_status = pr_state.status
            changed = True

        if pr_state.status == PullRequestStatus.APPROVED:
            if (
                run.execution_status != ExecutionStatus.DOCS_STAGED
                or run.rag_status != RagStatus.PROVISIONAL
                or run.knowledge_artifact_json is None
            ):
                run.execution_status = ExecutionStatus.PR_APPROVED
                artifact = self._knowledge_agent.capture(run)
                try:
                    receipt_payload = await self._tool_runtime.execute(
                        "rag.stage_provisional_artifact",
                        {"artifact": artifact.model_dump(mode="json")},
                    )
                    receipt = parse_rag_receipt(receipt_payload)
                except ToolExecutionError as exc:
                    run.knowledge_artifact_json = self._append_rag_receipt(
                        artifact,
                        operation="stage_provisional",
                        status="failed",
                        metadata={"error": str(exc)},
                    ).model_dump(mode="json")
                    run.rag_status = RagStatus.FAILED
                    run.failure_details = f"RAG provisional ingestion failed: {exc}"
                    changed = True
                    return changed

                artifact = self._record_rag_receipt(artifact, receipt)
                run.knowledge_artifact_json = artifact.model_dump(mode="json")
                run.rag_status = RagStatus.PROVISIONAL
                run.execution_status = ExecutionStatus.DOCS_STAGED
                run.failure_details = None
                await self._platform_recorder.record_artifact_state(
                    run,
                    artifact=artifact,
                    status="provisional",
                )
                changed = True
        elif pr_state.status == PullRequestStatus.MERGED:
            if run.execution_status not in {ExecutionStatus.MERGED, ExecutionStatus.COMPLETED}:
                run.execution_status = ExecutionStatus.MERGED
                if run.knowledge_artifact_json:
                    artifact = KnowledgeCaptureArtifact.model_validate(run.knowledge_artifact_json)
                    promoted_artifact = self._knowledge_agent.promote(artifact)
                    try:
                        receipt_payload = await self._tool_runtime.execute(
                            "rag.promote_artifact",
                            {"artifact": promoted_artifact.model_dump(mode="json")},
                        )
                        receipt = parse_rag_receipt(receipt_payload)
                    except ToolExecutionError as exc:
                        run.knowledge_artifact_json = self._append_rag_receipt(
                            promoted_artifact,
                            operation="promote",
                            status="failed",
                            metadata={"error": str(exc)},
                        ).model_dump(mode="json")
                        run.rag_status = RagStatus.FAILED
                        run.failure_details = f"RAG promotion failed: {exc}"
                        changed = True
                        return changed

                    promoted_artifact = self._record_rag_receipt(promoted_artifact, receipt)
                    run.knowledge_artifact_json = promoted_artifact.model_dump(mode="json")
                    run.rag_status = RagStatus.PROMOTED
                    run.execution_status = ExecutionStatus.COMPLETED
                    run.failure_details = None
                    await self._platform_recorder.record_artifact_state(
                        run,
                        artifact=promoted_artifact,
                        status="promoted",
                    )
                changed = True
        elif pr_state.status in {
            PullRequestStatus.CHANGES_REQUESTED,
            PullRequestStatus.DISMISSED,
            PullRequestStatus.CLOSED,
        }:
            if run.knowledge_artifact_json:
                artifact = KnowledgeCaptureArtifact.model_validate(run.knowledge_artifact_json)
                reason = (
                    "Pull request review is no longer in an approved state."
                    if pr_state.status != PullRequestStatus.CLOSED
                    else "Pull request closed before merge."
                )
                stale_artifact = self._knowledge_agent.mark_stale(
                    artifact,
                    reason=reason,
                    status=pr_state.status,
                )
                try:
                    receipt_payload = await self._tool_runtime.execute(
                        "rag.mark_artifact_stale",
                        {
                            "artifact": stale_artifact.model_dump(mode="json"),
                            "reason": reason,
                        },
                    )
                    receipt = parse_rag_receipt(receipt_payload)
                    stale_artifact = self._record_rag_receipt(stale_artifact, receipt)
                    run.rag_status = RagStatus.STALE
                except ToolExecutionError as exc:
                    stale_artifact = self._append_rag_receipt(
                        stale_artifact,
                        operation="mark_stale",
                        status="failed",
                        metadata={"reason": reason, "error": str(exc)},
                    )
                    run.rag_status = RagStatus.FAILED
                    run.failure_details = f"RAG stale-mark failed: {exc}"
                run.knowledge_artifact_json = stale_artifact.model_dump(mode="json")
                await self._platform_recorder.record_artifact_state(
                    run,
                    artifact=stale_artifact,
                    status="stale" if run.rag_status == RagStatus.STALE else "failed",
                )
            if pr_state.status != PullRequestStatus.CLOSED:
                run.execution_status = ExecutionStatus.PR_OPEN
            else:
                run.execution_status = ExecutionStatus.FAILED
                run.failure_details = "Pull request closed before merge."
            changed = True

        if changed:
            logger.info(
                "Pull request state applied to orchestration run",
                extra={
                    "event": "orchestration_pr_state_applied",
                    "run_id": run.id,
                    "repo": run.repo,
                    "source": pr_state.source,
                    "pr_status": {
                        "from": previous_pr_status.value,
                        "to": run.pr_status.value,
                    },
                    "execution_status": {
                        "from": previous_execution_status.value,
                        "to": run.execution_status.value,
                    },
                    "rag_status": {
                        "from": previous_rag_status.value,
                        "to": run.rag_status.value,
                    },
                },
            )

        return changed

    async def _require_run(self, run_id: str) -> OrchestrationRun:
        run = await self._repository.get(run_id)
        if run is None:
            logger.info(
                "Requested orchestration run was not found",
                extra={
                    "event": "orchestration_run_not_found",
                    "run_id": run_id,
                },
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
        return run

    def _build_run_summary(self, run: OrchestrationRun) -> str:
        if run.execution_status == ExecutionStatus.AWAITING_APPROVAL:
            proposal = ExecutionProposal.model_validate(run.proposal_json)
            if proposal.worker_target == WorkerTarget.AGENT_C:
                return "Waiting for Control Hub approval before Agent C can generate artifacts."
            return "Waiting for Control Hub approval before Worker B can execute."
        if run.execution_status == ExecutionStatus.PR_OPEN:
            return "Worker B opened a pull request and is waiting for human review."
        if run.execution_status == ExecutionStatus.DOCS_STAGED:
            proposal = ExecutionProposal.model_validate(run.proposal_json)
            if proposal.worker_target == WorkerTarget.AGENT_C and run.pr_number is None:
                return "Agent C generated and staged provisional artifacts directly."
            return "Agent C has staged provisional docs and RAG artifacts pending merge."
        if run.execution_status == ExecutionStatus.COMPLETED:
            return "Run completed and provisional knowledge has been promoted after merge."
        if run.execution_status == ExecutionStatus.REJECTED:
            return f"Run was rejected before execution. {run.failure_details or ''}".strip()
        if run.execution_status == ExecutionStatus.FAILED:
            return f"Run failed. {run.failure_details or ''}".strip()
        return f"Run is currently in '{run.execution_status.value}' state."

    def _default_requested_by(self) -> str:
        agent_a_profile = settings.agent_registry.get_agent("agent_a")
        if agent_a_profile is not None and agent_a_profile.requested_by:
            return agent_a_profile.requested_by
        return settings.orchestration_default_requested_by

    def _default_assigned_to(self) -> str | None:
        worker_b_profile = settings.agent_registry.get_agent("worker_b")
        if worker_b_profile is not None and worker_b_profile.assigned_to:
            return worker_b_profile.assigned_to
        return settings.orchestration_default_assigned_to

    def _build_branch_strategy(
        self,
        *,
        repo: str,
        project: ProjectContext | None,
        worker_target: WorkerTarget,
        run_id: str,
    ) -> str:
        repo_component = self._sanitize_branch_component(repo)
        project_component = self._derive_project_component(project)
        target_component = self._sanitize_branch_component(worker_target.value)
        run_component = self._sanitize_branch_component(run_id)[:12]
        return (
            f"orchestration/{repo_component}/{project_component}/{target_component}/{run_component}"
        )

    def _derive_project_component(self, project: ProjectContext | None) -> str:
        if project is None:
            return "default"

        candidate = project.project_slug or project.project_id
        if not candidate and project.project_path:
            candidate = PurePosixPath(project.project_path).name

        return self._sanitize_branch_component(candidate or "default")

    def _sanitize_branch_component(self, value: str) -> str:
        sanitized = "".join(char.lower() if char.isalnum() else "-" for char in value)
        collapsed = "-".join(part for part in sanitized.split("-") if part)
        return collapsed or "default"

    def _record_rag_receipt(
        self,
        artifact: KnowledgeCaptureArtifact,
        receipt: RagIngestionReceipt,
    ) -> KnowledgeCaptureArtifact:
        return self._append_rag_receipt(
            artifact,
            operation=receipt.operation,
            status=receipt.status,
            metadata={
                "remote_id": receipt.remote_id,
                **receipt.metadata,
            },
        )

    def _append_rag_receipt(
        self,
        artifact: KnowledgeCaptureArtifact,
        *,
        operation: str,
        status: str,
        metadata: dict[str, object] | None = None,
    ) -> KnowledgeCaptureArtifact:
        return artifact.model_copy(
            update={
                "promotion_history": [
                    *artifact.promotion_history,
                    {
                        "event": f"rag_{operation}",
                        "status": status,
                        "timestamp": datetime.now(UTC).isoformat(),
                        **(metadata or {}),
                    },
                ]
            }
        )
