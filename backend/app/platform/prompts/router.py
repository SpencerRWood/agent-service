from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.session import get_db
from app.platform.prompts.repository import PromptRepository
from app.platform.prompts.schemas import PromptCreate, PromptRead
from app.platform.prompts.service import PromptService

router = APIRouter(prefix="/prompts", tags=["platform-prompts"])


def get_prompt_service(db: AsyncSession = Depends(get_db)) -> PromptService:
    return PromptService(PromptRepository(db))


@router.post("/", response_model=PromptRead, status_code=201)
async def create_prompt(
    request: PromptCreate,
    service: PromptService = Depends(get_prompt_service),
) -> PromptRead:
    return await service.create_prompt(request)


@router.get("/{prompt_id}", response_model=PromptRead)
async def get_prompt(
    prompt_id: str,
    service: PromptService = Depends(get_prompt_service),
) -> PromptRead:
    return await service.get_prompt(prompt_id)
