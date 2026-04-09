from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.session import get_db
from app.platform.runs.repository import RunRepository
from app.platform.runs.schemas import RunCreate, RunRead, RunStepCreate, RunStepRead
from app.platform.runs.service import RunService

router = APIRouter(prefix="/runs", tags=["platform-runs"])


def get_run_service(db: AsyncSession = Depends(get_db)) -> RunService:
    return RunService(RunRepository(db))


@router.post("/", response_model=RunRead, status_code=201)
async def create_run(
    request: RunCreate,
    service: RunService = Depends(get_run_service),
) -> RunRead:
    return await service.create_run(request)


@router.get("/{run_id}", response_model=RunRead)
async def get_run(
    run_id: str,
    service: RunService = Depends(get_run_service),
) -> RunRead:
    return await service.get_run(run_id)


@router.post("/{run_id}/steps", response_model=RunStepRead, status_code=201)
async def create_run_step(
    run_id: str,
    request: RunStepCreate,
    service: RunService = Depends(get_run_service),
) -> RunStepRead:
    return await service.create_step(run_id, request)


@router.get("/{run_id}/steps", response_model=list[RunStepRead])
async def list_run_steps(
    run_id: str,
    service: RunService = Depends(get_run_service),
) -> list[RunStepRead]:
    return await service.list_steps(run_id)
