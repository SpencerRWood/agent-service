from fastapi import HTTPException, status

from app.platform.approvals.models import ApprovalDecision, ApprovalRequest
from app.platform.approvals.repository import ApprovalRepository
from app.platform.approvals.schemas import (
    ApprovalDecisionCreate,
    ApprovalDecisionRead,
    ApprovalRequestCreate,
    ApprovalRequestRead,
)


class ApprovalService:
    def __init__(self, repository: ApprovalRepository) -> None:
        self._repository = repository

    async def create_request(self, request: ApprovalRequestCreate) -> ApprovalRequestRead:
        approval = ApprovalRequest(
            run_id=request.run_id,
            run_step_id=request.run_step_id,
            target_type=request.target_type,
            target_id=request.target_id,
            reason=request.reason,
            decision_type=request.decision_type,
            policy_key=request.policy_key,
            request_payload_json=request.requested_decision,
            expires_at=request.expires_at,
            status="pending",
        )
        created = await self._repository.create_request(approval)
        return ApprovalRequestRead.model_validate(created)

    async def get_request(self, approval_id: str) -> ApprovalRequestRead:
        approval = await self._repository.get_request(approval_id)
        if approval is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
        return ApprovalRequestRead.model_validate(approval)

    async def create_decision(
        self,
        approval_id: str,
        request: ApprovalDecisionCreate,
    ) -> ApprovalDecisionRead:
        approval = await self._repository.get_request(approval_id)
        if approval is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
        if approval.status not in {"pending", "requested"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Approval is not in a decisionable state",
            )

        approval.status = "approved" if request.decision == "approved" else "rejected"
        await self._repository.update_request(approval)

        decision = ApprovalDecision(
            approval_request_id=approval_id,
            decision=request.decision,
            decided_by=request.decided_by,
            comment=request.comment,
            decision_payload_json=request.payload,
        )
        created = await self._repository.create_decision(decision)
        return ApprovalDecisionRead.model_validate(created)
