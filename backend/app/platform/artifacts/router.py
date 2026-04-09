from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.session import get_db
from app.platform.artifacts.repository import ArtifactRepository
from app.platform.artifacts.schemas import ArtifactCreate, ArtifactRead
from app.platform.artifacts.service import ArtifactService

router = APIRouter(tags=["platform-artifacts"])


def get_artifact_service(db: AsyncSession = Depends(get_db)) -> ArtifactService:
    return ArtifactService(ArtifactRepository(db))


@router.post("/artifacts", response_model=ArtifactRead, status_code=201)
async def create_artifact(
    request: ArtifactCreate,
    service: ArtifactService = Depends(get_artifact_service),
) -> ArtifactRead:
    return await service.create(request)


@router.get("/runs/{run_id}/artifacts", response_model=list[ArtifactRead])
async def list_run_artifacts(
    run_id: str,
    service: ArtifactService = Depends(get_artifact_service),
) -> list[ArtifactRead]:
    return await service.list_for_run(run_id)
