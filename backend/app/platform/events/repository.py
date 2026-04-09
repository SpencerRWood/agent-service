from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.events.models import Event


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, event: Event) -> Event:
        self._session.add(event)
        await self._session.commit()
        await self._session.refresh(event)
        return event

    async def list_for_run(self, run_id: str) -> Sequence[Event]:
        result = await self._session.execute(
            select(Event).where(Event.run_id == run_id).order_by(Event.created_at.asc())
        )
        return result.scalars().all()
