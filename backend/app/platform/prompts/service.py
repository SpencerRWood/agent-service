from fastapi import HTTPException, status

from app.platform.prompts.models import Prompt
from app.platform.prompts.repository import PromptRepository
from app.platform.prompts.schemas import PromptCreate, PromptRead


class PromptService:
    def __init__(self, repository: PromptRepository) -> None:
        self._repository = repository

    async def create_prompt(self, request: PromptCreate) -> PromptRead:
        prompt = Prompt(
            conversation_id=request.conversation_id,
            submitted_by=request.submitted_by,
            content=request.content,
            context_json=request.context,
            attachments_json=request.attachments,
            status="received",
        )
        created = await self._repository.create(prompt)
        return PromptRead.model_validate(created)

    async def get_prompt(self, prompt_id: str) -> PromptRead:
        prompt = await self._repository.get(prompt_id)
        if prompt is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found")
        return PromptRead.model_validate(prompt)
