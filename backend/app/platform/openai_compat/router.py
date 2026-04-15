from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.platform.agent_tasks.task_store import TaskStore, get_task_store
from app.platform.agents.service import (
    get_agent_registry,
    get_runtime_registry,
)
from app.platform.openai_compat.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    OpenAIModelList,
)
from app.platform.openai_compat.service import OpenAICompatService

router = APIRouter(prefix="/v1", tags=["public-openai-compat"])


def get_openai_compat_service(
    task_store: TaskStore = Depends(get_task_store),
) -> OpenAICompatService:
    return OpenAICompatService(
        agent_registry=get_agent_registry(),
        runtime_registry=get_runtime_registry(),
        task_store=task_store,
    )


@router.get("/models", response_model=OpenAIModelList)
async def list_models(
    service: OpenAICompatService = Depends(get_openai_compat_service),
) -> OpenAIModelList:
    return service.list_models()


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(
    request: ChatCompletionRequest,
    service: OpenAICompatService = Depends(get_openai_compat_service),
) -> ChatCompletionResponse | StreamingResponse:
    return await service.create_chat_completion(request)
