from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.artifacts.models import Artifact


class ArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, artifact: Artifact) -> Artifact:
        self._session.add(artifact)
        await self._session.commit()
        await self._session.refresh(artifact)
        return artifact

    async def list_for_run(self, run_id: str) -> Sequence[Artifact]:
        result = await self._session.execute(
            select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.created_at.asc())
        )
        return result.scalars().all()
