from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.runs.models import Run, RunStep


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(self, run: Run) -> Run:
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def get_run(self, run_id: str) -> Run | None:
        return await self._session.get(Run, run_id)

    async def create_step(self, step: RunStep) -> RunStep:
        self._session.add(step)
        await self._session.commit()
        await self._session.refresh(step)
        return step

    async def update_run(self, run: Run) -> Run:
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def get_step(self, step_id: str) -> RunStep | None:
        return await self._session.get(RunStep, step_id)

    async def update_step(self, step: RunStep) -> RunStep:
        await self._session.commit()
        await self._session.refresh(step)
        return step

    async def list_steps(self, run_id: str) -> Sequence[RunStep]:
        result = await self._session.execute(
            select(RunStep)
            .where(RunStep.run_id == run_id)
            .order_by(RunStep.sequence_index.asc(), RunStep.created_at.asc())
        )
        return result.scalars().all()
