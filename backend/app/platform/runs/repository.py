from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.runs.models import Run, RunStep


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(self, run: Run) -> Run:
        self._session.add(run)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise
        await self._session.refresh(run)
        return run

    async def get_run(self, run_id: str) -> Run | None:
        return await self._session.get(Run, run_id)

    async def get_run_by_idempotency_key(self, idempotency_key: str) -> Run | None:
        result = await self._session.execute(
            select(Run).where(Run.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

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

    async def list_recent_steps(self, *, limit: int = 50) -> Sequence[RunStep]:
        result = await self._session.execute(
            select(RunStep).order_by(RunStep.created_at.desc()).limit(limit)
        )
        return result.scalars().all()

    async def list_recent_runs(self, *, limit: int = 50) -> Sequence[Run]:
        result = await self._session.execute(
            select(Run).order_by(Run.created_at.desc()).limit(limit)
        )
        return result.scalars().all()
