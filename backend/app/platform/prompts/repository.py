from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.prompts.models import Prompt


class PromptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, prompt: Prompt) -> Prompt:
        self._session.add(prompt)
        await self._session.commit()
        await self._session.refresh(prompt)
        return prompt

    async def get(self, prompt_id: str) -> Prompt | None:
        return await self._session.get(Prompt, prompt_id)
