from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.approvals.models import ApprovalDecision, ApprovalRequest


class ApprovalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_request(self, approval: ApprovalRequest) -> ApprovalRequest:
        self._session.add(approval)
        await self._session.commit()
        await self._session.refresh(approval)
        return approval

    async def get_request(self, approval_id: str) -> ApprovalRequest | None:
        return await self._session.get(ApprovalRequest, approval_id)

    async def update_request(self, approval: ApprovalRequest) -> ApprovalRequest:
        await self._session.commit()
        await self._session.refresh(approval)
        return approval

    async def create_decision(self, decision: ApprovalDecision) -> ApprovalDecision:
        self._session.add(decision)
        await self._session.commit()
        await self._session.refresh(decision)
        return decision
