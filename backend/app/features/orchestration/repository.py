from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.orchestration.models import OrchestrationRun


class OrchestrationRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run: OrchestrationRun) -> OrchestrationRun:
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def update(self, run: OrchestrationRun) -> OrchestrationRun:
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def get(self, run_id: str) -> OrchestrationRun | None:
        return await self._session.get(OrchestrationRun, run_id)

    async def list(self, *, limit: int = 50, offset: int = 0) -> Sequence[OrchestrationRun]:
        stmt = (
            select(OrchestrationRun)
            .order_by(OrchestrationRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
