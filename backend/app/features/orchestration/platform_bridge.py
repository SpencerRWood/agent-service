from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.orchestration.models import OrchestrationRun
from app.features.orchestration.schemas import (
    ApprovedWorkPackage,
    KnowledgeCaptureArtifact,
    PullRequestState,
)
from app.platform.approvals.models import ApprovalDecision, ApprovalRequest
from app.platform.artifacts.models import Artifact
from app.platform.events.models import Event
from app.platform.invocations.models import ToolInvocation
from app.platform.prompts.models import Prompt
from app.platform.runs.models import Run, RunStep


class PlatformRecorder(Protocol):
    async def record_run_created(
        self,
        run: OrchestrationRun,
        *,
        requested_by: str,
        assigned_to: str | None,
    ) -> None: ...

    async def record_retry_requested(
        self, run: OrchestrationRun, *, reason: str | None
    ) -> None: ...

    async def record_approval_resolved(
        self,
        run: OrchestrationRun,
        *,
        decision: str,
        reason: str | None,
        source: str,
    ) -> None: ...

    async def record_dispatch_started(
        self,
        run: OrchestrationRun,
        *,
        executor_name: str,
        work_package: ApprovedWorkPackage,
    ) -> None: ...

    async def record_execution_result(self, run: OrchestrationRun) -> None: ...

    async def record_execution_failure(self, run: OrchestrationRun, *, detail: str) -> None: ...

    async def record_artifact_state(
        self,
        run: OrchestrationRun,
        *,
        artifact: KnowledgeCaptureArtifact,
        status: str,
    ) -> None: ...

    async def record_pull_request_event(
        self,
        run: OrchestrationRun,
        *,
        pr_state: PullRequestState,
    ) -> None: ...


class NullPlatformRecorder:
    async def record_run_created(
        self,
        run: OrchestrationRun,
        *,
        requested_by: str,
        assigned_to: str | None,
    ) -> None:
        return None

    async def record_retry_requested(self, run: OrchestrationRun, *, reason: str | None) -> None:
        return None

    async def record_approval_resolved(
        self,
        run: OrchestrationRun,
        *,
        decision: str,
        reason: str | None,
        source: str,
    ) -> None:
        return None

    async def record_dispatch_started(
        self,
        run: OrchestrationRun,
        *,
        executor_name: str,
        work_package: ApprovedWorkPackage,
    ) -> None:
        return None

    async def record_execution_result(self, run: OrchestrationRun) -> None:
        return None

    async def record_execution_failure(self, run: OrchestrationRun, *, detail: str) -> None:
        return None

    async def record_artifact_state(
        self,
        run: OrchestrationRun,
        *,
        artifact: KnowledgeCaptureArtifact,
        status: str,
    ) -> None:
        return None

    async def record_pull_request_event(
        self,
        run: OrchestrationRun,
        *,
        pr_state: PullRequestState,
    ) -> None:
        return None


class SqlPlatformRecorder:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_run_created(
        self,
        run: OrchestrationRun,
        *,
        requested_by: str,
        assigned_to: str | None,
    ) -> None:
        prompt = Prompt(
            id=str(uuid4()),
            content=run.user_prompt,
            submitted_by=requested_by,
            context_json={
                "repo": run.repo,
                "proposal": run.proposal_json,
                "source_metadata": run.source_metadata_json or {},
                "assigned_to": assigned_to,
            },
            attachments_json=[],
            status="received",
        )
        platform_run = Run(id=str(uuid4()), status=run.execution_status.value)
        approval = ApprovalRequest(
            id=str(uuid4()),
            run_id=platform_run.id,
            target_type="orchestration_run",
            target_id=run.id,
            status="pending",
            decision_type="yes_no",
            policy_key="orchestration.execute",
            reason=run.risk_summary,
            request_payload_json={
                "control_hub_approval_id": run.control_hub_approval_id,
                "proposal": run.proposal_json,
            },
        )
        approval_step = RunStep(
            id=str(uuid4()),
            run_id=platform_run.id,
            step_type="approval_checkpoint",
            title="Await approval before execution",
            status="blocked_on_approval",
            sequence_index=0,
            input_json={"proposal": run.proposal_json},
            approval_request_id=approval.id,
        )
        event = Event(
            id=str(uuid4()),
            run_id=platform_run.id,
            run_step_id=approval_step.id,
            entity_type="run",
            entity_id=platform_run.id,
            event_type="approval.requested",
            payload_json={"orchestration_run_id": run.id, "repo": run.repo},
            actor_type="system",
            actor_id="orchestration-service",
        )
        self._session.add_all([prompt, platform_run, approval, approval_step, event])
        await self._session.flush()
        platform_run.prompt_id = prompt.id
        self._store_refs(
            run,
            prompt_id=prompt.id,
            run_id=platform_run.id,
            latest_approval_request_id=approval.id,
            latest_approval_step_id=approval_step.id,
        )
        await self._session.commit()

    async def record_retry_requested(self, run: OrchestrationRun, *, reason: str | None) -> None:
        platform_run_id = self._ref(run, "run_id")
        if platform_run_id is None:
            return
        approval = ApprovalRequest(
            id=str(uuid4()),
            run_id=platform_run_id,
            target_type="orchestration_run",
            target_id=run.id,
            status="pending",
            decision_type="yes_no",
            policy_key="orchestration.execute",
            reason=reason or run.plan_summary,
            request_payload_json={
                "control_hub_approval_id": run.control_hub_approval_id,
                "retry": True,
                "proposal": run.proposal_json,
            },
        )
        step = RunStep(
            id=str(uuid4()),
            run_id=platform_run_id,
            step_type="approval_checkpoint",
            title="Retry approval checkpoint",
            status="blocked_on_approval",
            sequence_index=99,
            input_json={"retry_reason": reason},
            approval_request_id=approval.id,
        )
        event = Event(
            id=str(uuid4()),
            run_id=platform_run_id,
            run_step_id=step.id,
            entity_type="approval_request",
            entity_id=approval.id,
            event_type="approval.requested",
            payload_json={"retry": True, "orchestration_run_id": run.id},
            actor_type="system",
            actor_id="orchestration-service",
        )
        self._session.add_all([approval, step, event])
        self._store_refs(
            run,
            latest_approval_request_id=approval.id,
            latest_approval_step_id=step.id,
        )
        await self._session.commit()

    async def record_approval_resolved(
        self,
        run: OrchestrationRun,
        *,
        decision: str,
        reason: str | None,
        source: str,
    ) -> None:
        approval_id = self._ref(run, "latest_approval_request_id")
        platform_run_id = self._ref(run, "run_id")
        if approval_id is None or platform_run_id is None:
            return
        approval = await self._session.get(ApprovalRequest, approval_id)
        platform_run = await self._session.get(Run, platform_run_id)
        if approval is not None:
            approval.status = decision
        if platform_run is not None:
            platform_run.status = run.execution_status.value
        decision_record = ApprovalDecision(
            id=str(uuid4()),
            approval_request_id=approval_id,
            decision=decision,
            decided_by=source,
            comment=reason,
            decision_payload_json={"source": source, "reason": reason},
        )
        event = Event(
            id=str(uuid4()),
            run_id=platform_run_id,
            run_step_id=self._ref(run, "latest_approval_step_id"),
            entity_type="approval_request",
            entity_id=approval_id,
            event_type=f"approval.{decision}",
            payload_json={"reason": reason, "source": source},
            actor_type="system",
            actor_id=source,
        )
        self._session.add_all([decision_record, event])
        await self._session.commit()

    async def record_dispatch_started(
        self,
        run: OrchestrationRun,
        *,
        executor_name: str,
        work_package: ApprovedWorkPackage,
    ) -> None:
        platform_run_id = self._ref(run, "run_id")
        if platform_run_id is None:
            return
        step = RunStep(
            id=str(uuid4()),
            run_id=platform_run_id,
            step_type="tool_invocation",
            title=f"Invoke {executor_name}",
            status="running",
            sequence_index=100,
            input_json=work_package.model_dump(mode="json"),
        )
        invocation = ToolInvocation(
            id=str(uuid4()),
            run_id=platform_run_id,
            run_step_id=step.id,
            tool_name="agent.execute_coding_task",
            tool_version="2026-04-09",
            status="running",
            input_json=work_package.model_dump(mode="json"),
            normalized_input_json=work_package.model_dump(mode="json"),
            executor_name=executor_name,
            requested_by="orchestration-service",
        )
        event = Event(
            id=str(uuid4()),
            run_id=platform_run_id,
            run_step_id=step.id,
            entity_type="tool_invocation",
            entity_id=invocation.id,
            event_type="tool.invocation.started",
            payload_json={"executor_name": executor_name, "repo": run.repo},
            actor_type="system",
            actor_id="orchestration-service",
        )
        self._session.add_all([step, invocation, event])
        self._store_refs(
            run,
            latest_tool_step_id=step.id,
            latest_tool_invocation_id=invocation.id,
        )
        await self._session.commit()

    async def record_execution_result(self, run: OrchestrationRun) -> None:
        await self._update_invocation_state(
            run,
            invocation_status="succeeded",
            event_type="tool.invocation.succeeded",
            payload=run.execution_result_json or {},
        )

    async def record_execution_failure(self, run: OrchestrationRun, *, detail: str) -> None:
        await self._update_invocation_state(
            run,
            invocation_status="failed",
            event_type="tool.invocation.failed",
            payload={"detail": detail},
        )

    async def record_artifact_state(
        self,
        run: OrchestrationRun,
        *,
        artifact: KnowledgeCaptureArtifact,
        status: str,
    ) -> None:
        platform_run_id = self._ref(run, "run_id")
        if platform_run_id is None:
            return
        artifact_id = self._ref(run, "latest_artifact_id")
        record = await self._session.get(Artifact, artifact_id) if artifact_id else None
        if record is None:
            record = Artifact(
                id=str(uuid4()),
                run_id=platform_run_id,
                run_step_id=self._ref(run, "latest_tool_step_id"),
                artifact_type="knowledge_capture",
                title=artifact.manifest.artifact_id,
                content_json=artifact.model_dump(mode="json"),
                provenance_json={"orchestration_run_id": run.id},
                status=status,
            )
            self._session.add(record)
            await self._session.flush()
            self._store_refs(run, latest_artifact_id=record.id)
        else:
            record.content_json = artifact.model_dump(mode="json")
            record.status = status

        event = Event(
            id=str(uuid4()),
            run_id=platform_run_id,
            run_step_id=self._ref(run, "latest_tool_step_id"),
            entity_type="artifact",
            entity_id=record.id,
            event_type="artifact.updated",
            payload_json={"status": status, "artifact_manifest_id": artifact.manifest.artifact_id},
            actor_type="system",
            actor_id="orchestration-service",
        )
        self._session.add(event)
        await self._session.commit()

    async def record_pull_request_event(
        self,
        run: OrchestrationRun,
        *,
        pr_state: PullRequestState,
    ) -> None:
        platform_run_id = self._ref(run, "run_id")
        if platform_run_id is None:
            return
        event = Event(
            id=str(uuid4()),
            run_id=platform_run_id,
            run_step_id=self._ref(run, "latest_tool_step_id"),
            entity_type="pull_request",
            entity_id=str(run.pr_number or ""),
            event_type="pull_request.state_changed",
            payload_json=pr_state.model_dump(mode="json"),
            actor_type="system",
            actor_id=pr_state.source,
        )
        self._session.add(event)
        await self._session.commit()

    async def _update_invocation_state(
        self,
        run: OrchestrationRun,
        *,
        invocation_status: str,
        event_type: str,
        payload: dict,
    ) -> None:
        platform_run_id = self._ref(run, "run_id")
        invocation_id = self._ref(run, "latest_tool_invocation_id")
        if platform_run_id is None:
            return
        invocation = (
            await self._session.get(ToolInvocation, invocation_id) if invocation_id else None
        )
        if invocation is not None:
            invocation.status = invocation_status
            if invocation_status == "succeeded":
                invocation.output_json = payload
            else:
                invocation.error_json = payload
        platform_run = await self._session.get(Run, platform_run_id)
        if platform_run is not None:
            platform_run.status = run.execution_status.value
        event = Event(
            id=str(uuid4()),
            run_id=platform_run_id,
            run_step_id=self._ref(run, "latest_tool_step_id"),
            entity_type="tool_invocation",
            entity_id=invocation_id or "",
            event_type=event_type,
            payload_json=payload,
            actor_type="system",
            actor_id="orchestration-service",
        )
        self._session.add(event)
        await self._session.commit()

    def _ref(self, run: OrchestrationRun, key: str) -> str | None:
        metadata = run.source_metadata_json or {}
        platform_refs = metadata.get("platform_refs")
        if not isinstance(platform_refs, dict):
            return None
        value = platform_refs.get(key)
        return value if isinstance(value, str) else None

    def _store_refs(self, run: OrchestrationRun, **refs: str) -> None:
        metadata = dict(run.source_metadata_json or {})
        platform_refs = dict(metadata.get("platform_refs") or {})
        platform_refs.update(refs)
        metadata["platform_refs"] = platform_refs
        run.source_metadata_json = metadata
