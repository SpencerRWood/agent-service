from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.session import get_db
from app.platform.approvals.repository import ApprovalRepository
from app.platform.approvals.schemas import (
    ApprovalDecisionCreate,
    ApprovalDecisionRead,
    ApprovalRequestCreate,
    ApprovalRequestRead,
)
from app.platform.approvals.service import ApprovalService

router = APIRouter(prefix="/approvals", tags=["platform-approvals"])


def get_approval_service(db: AsyncSession = Depends(get_db)) -> ApprovalService:
    return ApprovalService(ApprovalRepository(db))


@router.post("/", response_model=ApprovalRequestRead, status_code=201)
async def create_approval_request(
    request: ApprovalRequestCreate,
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalRequestRead:
    return await service.create_request(request)


@router.get("/{approval_id}", response_model=ApprovalRequestRead)
async def get_approval_request(
    approval_id: str,
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalRequestRead:
    return await service.get_request(approval_id)


@router.post("/{approval_id}/decisions", response_model=ApprovalDecisionRead, status_code=201)
async def create_approval_decision(
    approval_id: str,
    request: ApprovalDecisionCreate,
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalDecisionRead:
    return await service.create_decision(approval_id, request)
