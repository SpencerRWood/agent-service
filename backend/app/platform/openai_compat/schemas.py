from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OpenAIModelCard(BaseModel):
    id: str
    object: str = "model"
    owned_by: str = "agent-service"


class OpenAIModelList(BaseModel):
    object: str = "list"
    data: list[OpenAIModelCard]


class ChatMessage(BaseModel):
    role: str
    content: str | list[dict[str, Any]]


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatCompletionChoiceMessage(BaseModel):
    role: str = "assistant"
    content: str


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatCompletionChoiceMessage
    finish_reason: str = "stop"


class ChatTaskInfo(BaseModel):
    id: str
    state: str
    stream_url: str
    approve_url: str | None = None
    reject_url: str | None = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    model: str
    choices: list[ChatCompletionChoice]
    task: ChatTaskInfo | None = None
