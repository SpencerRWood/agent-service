from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

from app.platform.agent_tasks.schemas import AgentTaskCreateRequest
from app.platform.agent_tasks.task_store import TaskStore, to_public_task
from app.platform.agents.schemas import AgentDefinition
from app.platform.agents.service import AgentRegistry, RuntimeRegistry
from app.platform.openai_compat.schemas import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatTaskInfo,
    OpenAIModelCard,
    OpenAIModelList,
)


class OpenAICompatService:
    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        runtime_registry: RuntimeRegistry,
        task_store: TaskStore,
    ) -> None:
        self._agent_registry = agent_registry
        self._runtime_registry = runtime_registry
        self._task_store = task_store

    def list_models(self) -> OpenAIModelList:
        return OpenAIModelList(
            data=[OpenAIModelCard(id=agent.id) for agent in self._agent_registry.list_agents()]
        )

    async def create_chat_completion(
        self,
        request: ChatCompletionRequest,
    ) -> ChatCompletionResponse | StreamingResponse:
        agent = self._agent_registry.get_agent(request.model)
        runtime = self._runtime_registry.get_runtime(agent.runtime)
        prompt = _messages_to_prompt(request.messages, runtime.prompt_preamble)
        task_response = await self._task_store.create_task(
            AgentTaskCreateRequest(
                task_class=runtime.task_class,
                public_agent_id=agent.id,
                runtime_key=runtime.key,
                prompt=prompt,
                route_profile=runtime.route_profile,
                approval_policy={"mode": runtime.approval_mode},
                metadata={
                    **request.metadata,
                    "openai_model": agent.id,
                    "runtime_key": runtime.key,
                },
                wait_for_completion=_should_wait_inline(request=request, runtime=runtime),
            )
        )
        public_task = to_public_task(task_response.task)
        if request.stream and agent.supports_streaming:
            return StreamingResponse(
                self._stream_chat(task_id=task_response.task.task_id, model=agent.id),
                media_type="text/event-stream",
            )
        return self._build_response(agent, public_task)

    async def _stream_chat(self, *, task_id: str, model: str) -> AsyncIterator[str]:
        task = await self._task_store.get_public_task(task_id)
        task_payload = _task_payload(task)
        intro = {
            "id": f"chatcmpl_{task_id}",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}
            ],
            "task": task_payload,
        }
        yield f"data: {json.dumps(intro)}\n\n"

        sent_event_ids: set[str] = set()
        while True:
            full_task = await self._task_store.get_task(task_id)
            for event in full_task.events:
                if event.id in sent_event_ids:
                    continue
                sent_event_ids.add(event.id)
                message = str(event.payload_json.get("message") or "").strip()
                if not message:
                    continue
                chunk = {
                    "id": f"chatcmpl_{task_id}",
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [
                        {"index": 0, "delta": {"content": f"{message}\n"}, "finish_reason": None}
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
            public_task = to_public_task(full_task)
            if public_task.approval_pending or public_task.state in {
                "completed",
                "failed",
                "rejected",
            }:
                break
            await asyncio.sleep(1.0)

        final_content = public_task.summary or (
            "Task requires approval before execution can continue."
            if public_task.approval_pending
            else f"Task {public_task.state}."
        )
        final_chunk = {
            "id": f"chatcmpl_{task_id}",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": {"content": final_content}, "finish_reason": "stop"}],
            "task": _task_payload(public_task),
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    def _build_response(
        self,
        agent: AgentDefinition,
        task,
    ) -> ChatCompletionResponse:
        if task.approval_pending:
            content = "Task accepted but requires approval before execution can continue."
        elif task.state == "completed" and task.summary:
            content = task.summary
        else:
            content = "Task accepted. Follow the task stream for progress."
        return ChatCompletionResponse(
            id=f"chatcmpl_{task.task_id}",
            model=agent.id,
            choices=[
                ChatCompletionChoice(
                    message=ChatCompletionChoiceMessage(content=content),
                )
            ],
            task=ChatTaskInfo(
                id=task.task_id,
                state=task.state,
                stream_url=task.links.stream_url,
                approve_url=task.links.approve_url,
                reject_url=task.links.reject_url,
            ),
        )


def _messages_to_prompt(messages, prompt_preamble: str | None) -> str:
    rendered: list[str] = []
    if prompt_preamble:
        rendered.append(f"Runtime guidance: {prompt_preamble}")
    for message in messages:
        if isinstance(message.content, str):
            content = message.content
        else:
            content = json.dumps(message.content)
        rendered.append(f"{message.role.upper()}:\n{content}")
    return "\n\n".join(rendered).strip()


def _task_payload(task) -> dict:
    return {
        "id": task.task_id,
        "state": task.state,
        "stream_url": task.links.stream_url,
        "approve_url": task.links.approve_url,
        "reject_url": task.links.reject_url,
    }


def _should_wait_inline(*, request: ChatCompletionRequest, runtime) -> bool:
    del request, runtime
    # OpenWebUI may send non-streaming chat completion requests through the
    # OpenAI-compatible endpoint. Waiting for remote worker completion keeps
    # the origin request open long enough to trigger upstream proxy timeouts.
    # Return promptly and direct clients to the task stream for progress.
    return False
