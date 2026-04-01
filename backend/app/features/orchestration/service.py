from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol

from fastapi import HTTPException, status

from app.core.settings import settings
from app.features.orchestration.models import (
    ExecutionStatus,
    OrchestrationRun,
    ProviderName,
    PullRequestStatus,
    RagStatus,
    WorkerType,
)
from app.features.orchestration.schemas import (
    ActionType,
    ApprovedWorkPackage,
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
from app.integrations.providers.base import ProviderExecutionError
from app.integrations.providers.router import PolicyBasedProviderRouter, ProviderRoutingError


class PullRequestStateClient(Protocol):
    async def get_state(self, run: OrchestrationRun) -> PullRequestState | None: ...


class NullPullRequestStateClient:
    async def get_state(self, run: OrchestrationRun) -> PullRequestState | None:
        return None


class OrchestrationRepository(Protocol):
    async def create(self, run: OrchestrationRun) -> OrchestrationRun: ...

    async def update(self, run: OrchestrationRun) -> OrchestrationRun: ...

    async def get(self, run_id: str) -> OrchestrationRun | None: ...

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[OrchestrationRun]: ...


@dataclass
class AgentAResult:
    proposal: ExecutionProposal
    plan_summary: str
    risk_summary: str


class PlannerRiskAgent:
    def build_plan(self, request: CreateRunRequest) -> AgentAResult:
        repo = request.repo or settings.orchestration_default_repo
        worker_target = request.worker_target or WorkerTarget(
            settings.orchestration_default_worker_target
        )
        lowered = request.user_prompt.lower()
        risk_level = RiskLevel.HIGH if any(
            token in lowered for token in ["delete", "drop", "migrate", "auth", "billing"]
        ) else RiskLevel.MEDIUM
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


class KnowledgeCaptureAgent:
    def capture(self, run: OrchestrationRun) -> KnowledgeCaptureArtifact:
        return KnowledgeCaptureArtifact(
            implementation_summary=(
                f"PR {run.pr_number} for repo '{run.repo}' is approved and ready for merge promotion."
            ),
            operational_notes=[
                "Knowledge is provisional until the PR is merged.",
                "If PR approval is dismissed or changes are requested, mark the artifact stale.",
            ],
            decision_log=[
                f"Provider selected: {run.provider.value}",
                f"Control Hub approval: {run.control_hub_approval_id}",
            ],
            knowledge_chunks=[
                run.plan_summary,
                run.risk_summary,
                f"PR URL: {run.pr_url}",
            ],
            source_pr_url=run.pr_url or "",
            provisional=True,
        )


class OrchestrationService:
    def __init__(
        self,
        *,
        repository: OrchestrationRepository,
        control_hub_client: ControlHubClient,
        provider_router: PolicyBasedProviderRouter,
        pr_state_client: PullRequestStateClient | None = None,
        planner_agent: PlannerRiskAgent | None = None,
        knowledge_agent: KnowledgeCaptureAgent | None = None,
    ) -> None:
        self._repository = repository
        self._control_hub = control_hub_client
        self._provider_router = provider_router
        self._pr_state_client = pr_state_client or NullPullRequestStateClient()
        self._planner_agent = planner_agent or PlannerRiskAgent()
        self._knowledge_agent = knowledge_agent or KnowledgeCaptureAgent()

    async def create_run(self, request: CreateRunRequest) -> RunRead:
        agent_result = self._planner_agent.build_plan(request)
        try:
            provider_name = self._provider_router.choose_provider_name(agent_result.proposal)
        except ProviderRoutingError as exc:
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
                    requested_by=request.requested_by or settings.orchestration_default_requested_by,
                    assigned_to=request.assigned_to or settings.orchestration_default_assigned_to,
                )
            )
        except ControlHubIntegrationError as exc:
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
                    requested_by=settings.orchestration_default_requested_by,
                    assigned_to=settings.orchestration_default_assigned_to,
                )
            )
        except ControlHubIntegrationError as exc:
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
        return RunRead.model_validate(updated)

    async def reconcile_run(self, run_id: str) -> ReconcileResponse:
        run = await self._require_run(run_id)
        changed = False

        if run.control_hub_approval_id is not None:
            try:
                approval = await self._control_hub.get_approval(run.control_hub_approval_id)
            except ControlHubIntegrationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed to fetch Control Hub approval: {exc}",
                ) from exc
            if approval.status == ApprovalStatus.REJECTED and run.execution_status != ExecutionStatus.REJECTED:
                run.execution_status = ExecutionStatus.REJECTED
                run.failure_details = approval.decision_reason or "Control Hub approval rejected."
                run.rag_status = RagStatus.STALE if run.knowledge_artifact_json else RagStatus.NOT_STARTED
                changed = True
            elif (
                approval.status == ApprovalStatus.APPROVED
                and run.execution_status == ExecutionStatus.AWAITING_APPROVAL
            ):
                await self._dispatch_worker(run)
                changed = True

        pr_state = await self._pr_state_client.get_state(run)
        if pr_state is not None:
            changed = self._apply_pull_request_state(run, pr_state) or changed

        if changed:
            run = await self._repository.update(run)

        return ReconcileResponse(run=RunRead.model_validate(run), changed=changed)

    async def apply_pull_request_event(
        self, run_id: str, event: PullRequestEventRequest
    ) -> RunRead:
        run = await self._require_run(run_id)
        changed = self._apply_pull_request_state(
            run,
            PullRequestState(
                status=event.status,
                approved_by=event.approved_by,
                merged_at=event.merged_at,
                source=event.source,
            ),
        )
        if changed:
            run = await self._repository.update(run)
        return RunRead.model_validate(run)

    async def _dispatch_worker(self, run: OrchestrationRun) -> None:
        run.execution_status = ExecutionStatus.APPROVED
        proposal = ExecutionProposal.model_validate(run.proposal_json)
        primary_provider_name = run.provider
        work_package = self._build_work_package(run, proposal, primary_provider_name)
        run.work_package_json = work_package.model_dump(mode="json")
        run.execution_status = ExecutionStatus.EXECUTING

        try:
            provider = self._provider_router.get_provider(primary_provider_name)
            result = await provider.execute(work_package)
        except (ProviderExecutionError, ProviderRoutingError) as primary_exc:
            fallback_provider_name = self._provider_router.choose_fallback_name(primary_provider_name)
            if fallback_provider_name is None:
                run.execution_status = ExecutionStatus.FAILED
                run.failure_details = f"Worker execution failed: {primary_exc}"
                return

            fallback_work_package = self._build_work_package(run, proposal, fallback_provider_name)
            run.work_package_json = fallback_work_package.model_dump(mode="json")
            try:
                fallback_provider = self._provider_router.get_provider(fallback_provider_name)
                result = await fallback_provider.execute(fallback_work_package)
            except (ProviderExecutionError, ProviderRoutingError) as fallback_exc:
                run.execution_status = ExecutionStatus.FAILED
                run.failure_details = (
                    "Worker execution failed. "
                    f"Primary provider '{primary_provider_name.value}': {primary_exc}. "
                    f"Fallback provider '{fallback_provider_name.value}': {fallback_exc}."
                )
                return

            run.provider = fallback_provider_name
            result = result.model_copy(
                update={
                    "known_risks": [
                        f"Primary provider '{primary_provider_name.value}' failed and fallback provider '{fallback_provider_name.value}' handled execution.",
                        *result.known_risks,
                    ]
                }
            )
            self._apply_worker_result(run, result)
            return
        except Exception as exc:  # pragma: no cover - defensive guard
            run.execution_status = ExecutionStatus.FAILED
            run.failure_details = f"Worker execution failed: {exc}"
            return

        run.failure_details = None
        self._apply_worker_result(run, result)

    def _apply_worker_result(self, run: OrchestrationRun, result: WorkerExecutionResult) -> None:
        run.branch = result.branch_name
        run.pr_url = result.pr_url
        run.pr_number = result.pr_number
        run.pr_status = PullRequestStatus.OPEN
        run.execution_status = ExecutionStatus.PR_OPEN
        run.execution_result_json = result.model_dump(mode="json")

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

    def _apply_pull_request_state(self, run: OrchestrationRun, pr_state: PullRequestState) -> bool:
        changed = False
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
                run.knowledge_artifact_json = artifact.model_dump(mode="json")
                run.rag_status = RagStatus.PROVISIONAL
                run.execution_status = ExecutionStatus.DOCS_STAGED
                changed = True
        elif pr_state.status == PullRequestStatus.MERGED:
            if run.execution_status not in {ExecutionStatus.MERGED, ExecutionStatus.COMPLETED}:
                run.execution_status = ExecutionStatus.MERGED
                if run.knowledge_artifact_json:
                    run.rag_status = RagStatus.PROMOTED
                    run.execution_status = ExecutionStatus.COMPLETED
                changed = True
        elif pr_state.status in {
            PullRequestStatus.CHANGES_REQUESTED,
            PullRequestStatus.DISMISSED,
            PullRequestStatus.CLOSED,
        }:
            if run.knowledge_artifact_json:
                run.rag_status = RagStatus.STALE
            if pr_state.status != PullRequestStatus.CLOSED:
                run.execution_status = ExecutionStatus.PR_OPEN
            else:
                run.execution_status = ExecutionStatus.FAILED
                run.failure_details = "Pull request closed before merge."
            changed = True

        return changed

    async def _require_run(self, run_id: str) -> OrchestrationRun:
        run = await self._repository.get(run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
        return run

    def _build_run_summary(self, run: OrchestrationRun) -> str:
        if run.execution_status == ExecutionStatus.AWAITING_APPROVAL:
            return "Waiting for Control Hub approval before Worker B can execute."
        if run.execution_status == ExecutionStatus.PR_OPEN:
            return "Worker B opened a pull request and is waiting for human review."
        if run.execution_status == ExecutionStatus.DOCS_STAGED:
            return "Agent C has staged provisional docs and RAG artifacts pending merge."
        if run.execution_status == ExecutionStatus.COMPLETED:
            return "Run completed and provisional knowledge has been promoted after merge."
        if run.execution_status == ExecutionStatus.REJECTED:
            return f"Run was rejected before execution. {run.failure_details or ''}".strip()
        if run.execution_status == ExecutionStatus.FAILED:
            return f"Run failed. {run.failure_details or ''}".strip()
        return f"Run is currently in '{run.execution_status.value}' state."

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
        return f"orchestration/{repo_component}/{project_component}/{target_component}/{run_component}"

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
