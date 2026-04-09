from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.invocations.models import ToolInvocation


class ToolInvocationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, invocation: ToolInvocation) -> ToolInvocation:
        self._session.add(invocation)
        await self._session.commit()
        await self._session.refresh(invocation)
        return invocation

    async def get(self, invocation_id: str) -> ToolInvocation | None:
        return await self._session.get(ToolInvocation, invocation_id)
