"""
title: Agent Services Manifold Pipe
author: Spencer Wood
author_url: https://github.com/SpencerRWood
version: 0.4.3
"""

import json
import re
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field


class Pipe:
    _ENRICHMENT_PROMPT_PATTERNS = (
        re.compile(r"###\s*task:\s*generate\s+1-3\s+broad\s+tags", re.IGNORECASE),
        re.compile(
            r"###\s*task:\s*generate\s+a\s+concise,\s*3-5\s+word\s+title",
            re.IGNORECASE,
        ),
        re.compile(
            r"###\s*task:\s*suggest\s+3-5\s+relevant\s+follow(?:-|\s)?up\s+questions",
            re.IGNORECASE,
        ),
        re.compile(
            r"###\s*task:\s*suggest\s+3-5\s+relevant\s+follow(?:-|\s)?up\s+questions\s+or\s+prompts",
            re.IGNORECASE,
        ),
    )
    _TOOL_PROGRESS_PATTERNS = (
        re.compile(r"\btool\b", re.IGNORECASE),
        re.compile(r"\bfunction\b", re.IGNORECASE),
        re.compile(r"\binvok(?:e|ing|ed)\b", re.IGNORECASE),
        re.compile(r"\bsearch(?:ing)?\b", re.IGNORECASE),
        re.compile(r"\bread(?:ing)?\b", re.IGNORECASE),
        re.compile(r"\bedit(?:ing)?\b", re.IGNORECASE),
        re.compile(r"\bpatch(?:ing)?\b", re.IGNORECASE),
        re.compile(r"\btest(?:ing)?\b", re.IGNORECASE),
        re.compile(r"\bcommand\b", re.IGNORECASE),
        re.compile(r"\bshell\b", re.IGNORECASE),
    )
    _THINKING_PROGRESS_PATTERNS = (
        re.compile(r"\bthinking\b", re.IGNORECASE),
        re.compile(r"\breason(?:ing)?\b", re.IGNORECASE),
        re.compile(r"\banaly(?:sis|zing|sing)\b", re.IGNORECASE),
        re.compile(r"\bplanning\b", re.IGNORECASE),
        re.compile(r"\bdrafting\b", re.IGNORECASE),
    )

    class Valves(BaseModel):
        AGENT_BASE_URL: str = Field(
            default="https://agents.woodhost.cloud",
            description="Base URL for Agent Services",
        )
        CREATE_TIMEOUT_SECONDS: float = Field(
            default=30.0,
            description="Timeout for model listing, chat completion creation, and task readback",
        )
        STREAM_TIMEOUT_SECONDS: float = Field(
            default=900.0,
            description="Timeout for the public task SSE stream",
        )
        INCLUDE_DEBUG_BLOCK: bool = Field(
            default=True,
            description="Append task/debug metadata to the final response",
        )
        VERIFY_TLS: bool = Field(
            default=True,
            description="Verify TLS certificates for Agent Services",
        )
        EMIT_MAIN_TASK_THINKING: bool = Field(
            default=True,
            description="Show a concise visible thinking status for the primary response task",
        )
        EMIT_RAW_STREAM_EVENTS: bool = Field(
            default=True,
            description="Emit each agent task SSE event as a visible Open WebUI status update",
        )

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [
            {"id": "agent_services.planner", "name": "Agent Services / Planner"},
            {
                "id": "agent_services.rag_analyst",
                "name": "Agent Services / RAG Analyst",
            },
            {"id": "agent_services.coder", "name": "Agent Services / Coder"},
            {"id": "agent_services.reviewer", "name": "Agent Services / Reviewer"},
        ]

    def _extract_text_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    text = str(item.get("text", "")).strip()
                    if text:
                        parts.append(text)
            return "\n".join(parts).strip()

        return ""

    def _extract_prompt(self, body: dict[str, Any]) -> str:
        messages = body.get("messages", [])
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            text = self._extract_text_content(message.get("content", ""))
            if text:
                return text
        raise Exception("No user message found in request body.")

    def _extract_history(self, body: dict[str, Any]) -> list[dict[str, str]]:
        history: list[dict[str, str]] = []
        for message in body.get("messages", []):
            role = message.get("role")
            if role not in {"system", "user", "assistant"}:
                continue

            text = self._extract_text_content(message.get("content", ""))
            if text:
                history.append({"role": role, "content": text})
        return history

    def _resolve_model(self, model_id: str) -> str:
        lowered = str(model_id or "").strip().lower()

        aliases = {
            "auto": "planner",
            "planner": "planner",
            "rag_analyst": "rag-analyst",
            "rag-analyst": "rag-analyst",
            "coder": "coder",
            "reviewer": "reviewer",
        }

        for key, resolved in aliases.items():
            if lowered == key or lowered.endswith(f".{key}") or f".{key}." in lowered:
                return resolved

        return "planner"

    def _is_enrichment_prompt(self, prompt: str) -> bool:
        prompt = str(prompt or "").strip()
        if not prompt:
            return False
        return any(pattern.search(prompt) for pattern in self._ENRICHMENT_PROMPT_PATTERNS)

    def _classify_progress_message(self, message: Any) -> str | None:
        normalized = str(message or "").strip()
        if not normalized:
            return None
        if any(pattern.search(normalized) for pattern in self._TOOL_PROGRESS_PATTERNS):
            return "status"
        if any(pattern.search(normalized) for pattern in self._THINKING_PROGRESS_PATTERNS):
            return "thinking"
        return None

    def _stringify_value(self, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _format_progress_event(self, event_type: str, payload: dict[str, Any]) -> str | None:
        message = self._stringify_value(payload.get("message"))
        state = self._stringify_value(payload.get("state"))
        backend = self._stringify_value(payload.get("backend"))
        artifact_type = self._stringify_value(payload.get("artifact_type"))
        title = self._stringify_value(payload.get("title"))
        available = payload.get("available")

        details: list[str] = []
        if state:
            details.append(f"state={state}")
        if backend:
            details.append(f"backend={backend}")
        if artifact_type:
            details.append(f"artifact={artifact_type}")
        if title:
            details.append(f"title={title}")
        if available is not None:
            details.append(f"available={bool(available)}")

        if message:
            if details:
                return f"{event_type}: {message} ({', '.join(details)})"
            return f"{event_type}: {message}"

        if details:
            return f"{event_type} ({', '.join(details)})"

        return event_type

    def _format_named_event(
        self,
        event_name: str,
        event: dict[str, Any],
    ) -> str | None:
        if event_name == "progress":
            event_type = self._stringify_value(event.get("type")) or "progress"
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}
            return self._format_progress_event(event_type, payload)

        if event_name == "approval":
            status = self._stringify_value(event.get("status"))
            target_type = self._stringify_value(event.get("target_type"))
            reason = self._stringify_value(event.get("reason"))
            details = [part for part in (status, target_type, reason) if part]
            return (
                f"approval: {' | '.join(details)}"
                if details
                else "approval requested"
            )

        if event_name == "approval_decision":
            decision = self._stringify_value(event.get("decision"))
            comment = self._stringify_value(event.get("comment"))
            details = [part for part in (decision, comment) if part]
            return (
                f"approval_decision: {' | '.join(details)}"
                if details
                else "approval decision recorded"
            )

        if event_name == "artifact":
            artifact_type = self._stringify_value(event.get("type"))
            title = self._stringify_value(event.get("title"))
            details = [part for part in (artifact_type, title) if part]
            return f"artifact: {' | '.join(details)}" if details else "artifact created"

        if event_name == "terminal":
            status = self._stringify_value(event.get("status")) or "unknown"
            task_id = self._stringify_value(event.get("task_id"))
            return (
                f"terminal: status={status}, task_id={task_id}"
                if task_id
                else f"terminal: status={status}"
            )

        return None

    def _build_metadata(
        self,
        body: dict[str, Any],
        __user__: Optional[dict[str, Any]],
        prompt: str,
    ) -> dict[str, Any]:
        user = __user__ or {}

        metadata: dict[str, Any] = {
            "source": "openwebui_pipe",
            "client": {
                "name": "openwebui",
                "model_id": body.get("model"),
                "stream": bool(body.get("stream", True)),
                "conversation_id": body.get("conversation_id"),
                "message_id": body.get("id"),
            },
            "chat": {
                "id": body.get("chat_id"),
                "title": body.get("title"),
                "message_count": len(body.get("messages", [])),
            },
            "user": {
                "id": user.get("id"),
                "name": user.get("name"),
                "email": user.get("email"),
                "role": user.get("role"),
            },
            "request": {
                "prompt": prompt,
                "history": self._extract_history(body),
            },
            "options": {
                "temperature": body.get("temperature"),
                "top_p": body.get("top_p"),
                "max_tokens": body.get("max_tokens"),
                "seed": body.get("seed"),
            },
            "tags": body.get("tags") or [],
        }

        files = body.get("files")
        if files:
            metadata["files"] = files

        tool_ids = body.get("tool_ids")
        if tool_ids:
            metadata["tool_ids"] = tool_ids

        features = body.get("features")
        if features:
            metadata["features"] = features

        session_info = body.get("session_info")
        if session_info:
            metadata["session_info"] = session_info

        return metadata

    async def _emit_status(
        self,
        __event_emitter__,
        description: str,
        *,
        done: bool = False,
        hidden: bool = False,
        suppress: bool = False,
    ) -> None:
        if suppress:
            return
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": description,
                        "done": done,
                        "hidden": hidden,
                    },
                }
            )

    async def _emit_thinking(
        self,
        __event_emitter__,
        description: str,
        *,
        suppress: bool = False,
    ) -> None:
        if not self.valves.EMIT_MAIN_TASK_THINKING:
            return
        await self._emit_status(
            __event_emitter__,
            description,
            suppress=suppress,
        )

    async def _emit_notification(
        self,
        __event_emitter__,
        content: str,
        level: str = "info",
    ) -> None:
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "notification",
                    "data": {
                        "type": level,
                        "content": content,
                    },
                }
            )

    async def _list_models(self, client: httpx.AsyncClient) -> set[str]:
        response = await client.get("/api/v1/models")
        response.raise_for_status()
        payload = response.json()
        available = set()
        for item in payload.get("data", []):
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id.strip():
                available.add(model_id.strip())
        return available

    async def _create_completion(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = await client.post("/api/v1/chat/completions", json=payload)
        response.raise_for_status()
        return response.json()

    async def _read_task(
        self,
        client: httpx.AsyncClient,
        task_id: str,
    ) -> dict[str, Any]:
        response = await client.get(f"/api/agent-tasks/{task_id}")
        response.raise_for_status()
        return response.json()

    def _extract_completion_text(self, completion: dict[str, Any]) -> str:
        choices = completion.get("choices") or []
        if not choices:
            return ""

        first = choices[0] or {}
        message = first.get("message") or {}
        content = message.get("content")

        if isinstance(content, str):
            return content.strip()

        return ""

    def _task_block(self, task: dict[str, Any]) -> str:
        lines = [
            f"Task ID: `{task.get('id', 'unknown')}`",
            f"Task State: `{task.get('state', 'unknown')}`",
            f"Stream URL: `{task.get('stream_url', '')}`",
        ]

        approve_url = task.get("approve_url")
        reject_url = task.get("reject_url")

        if approve_url:
            lines.append(f"Approve URL: `{approve_url}`")
        if reject_url:
            lines.append(f"Reject URL: `{reject_url}`")

        return "\n".join(lines)

    async def _stream_task(
        self,
        client: httpx.AsyncClient,
        stream_url: str,
        __event_emitter__,
        *,
        suppress_status: bool = False,
        agent_label: str = "Agent",
    ) -> str:
        terminal_status = "unknown"
        last_visible_status: Optional[str] = None

        async def emit_visible_status(
            description: str,
            *,
            done: bool = False,
        ) -> None:
            nonlocal last_visible_status

            normalized = str(description or "").strip()
            if not normalized or normalized == last_visible_status:
                return

            last_visible_status = normalized
            await self._emit_status(
                __event_emitter__,
                normalized,
                done=done,
                suppress=suppress_status,
            )

        async def emit_visible_thinking(description: str) -> None:
            nonlocal last_visible_status

            normalized = str(description or "").strip()
            if not normalized or normalized == last_visible_status:
                return

            last_visible_status = normalized
            await self._emit_thinking(
                __event_emitter__,
                normalized,
                suppress=suppress_status,
            )

        async with client.stream("GET", stream_url) as response:
            response.raise_for_status()

            current_event: Optional[str] = None

            async for raw_line in response.aiter_lines():
                if raw_line is None:
                    continue

                line = raw_line.strip()
                if not line:
                    continue

                if line.startswith("event: "):
                    current_event = line[len("event: ") :]
                    continue

                if not line.startswith("data: "):
                    continue

                try:
                    event = json.loads(line[len("data: ") :])
                except json.JSONDecodeError:
                    continue

                if self.valves.EMIT_RAW_STREAM_EVENTS:
                    rendered_event = self._format_named_event(current_event or "", event)
                    if rendered_event:
                        await emit_visible_status(rendered_event)

                if current_event == "progress":
                    event_type = event.get("type")
                    payload = event.get("payload", {})
                    message = payload.get("message")
                    state = payload.get("state")

                    if event_type == "agent.task.awaiting_approval":
                        await emit_visible_status(
                            "Waiting for approval before execution can continue...",
                        )
                    elif (
                        event_type == "agent.task.state_changed"
                        and state == "preflight_check"
                        and not self.valves.EMIT_RAW_STREAM_EVENTS
                    ):
                        await emit_visible_thinking(
                            f"{agent_label} is analyzing your request...",
                        )
                    elif (
                        event_type == "agent.task.state_changed" and state == "running"
                        and not self.valves.EMIT_RAW_STREAM_EVENTS
                    ):
                        await emit_visible_thinking(
                            f"{agent_label} is drafting a response...",
                        )
                    elif event_type == "agent.task.deferred":
                        retry_after = payload.get("available_at") or payload.get(
                            "retry_after"
                        )
                        detail = "Task deferred."
                        if retry_after:
                            detail += f" Retry after {retry_after}."
                        raise Exception(detail)
                    elif event_type == "agent.task.failed":
                        raise Exception(message or "Task failed.")
                    else:
                        message_kind = self._classify_progress_message(message)
                        if message_kind == "thinking" and not self.valves.EMIT_RAW_STREAM_EVENTS:
                            await emit_visible_thinking(message)
                        elif message_kind == "status" and not self.valves.EMIT_RAW_STREAM_EVENTS:
                            await emit_visible_status(message)

                elif current_event == "approval":
                    await emit_visible_status(
                        "Approval is required before execution can continue.",
                    )

                elif current_event == "approval_decision":
                    decision = event.get("decision")
                    if decision == "approved":
                        await emit_visible_status(
                            "Approval recorded. Continuing execution...",
                        )
                    elif decision == "rejected":
                        await emit_visible_status(
                            "Task approval was rejected.",
                        )

                elif current_event == "artifact":
                    artifact_type = str(event.get("type") or "").strip()
                    title = str(event.get("title") or "").strip()
                    if artifact_type and artifact_type != "execution_result":
                        label = title or artifact_type.replace("_", " ")
                        await emit_visible_status(f"Produced {label}.")

                elif current_event == "terminal":
                    terminal_status = (
                        str(event.get("status") or "unknown").strip() or "unknown"
                    )
                    break

        return terminal_status

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: Optional[dict[str, Any]] = None,
        __event_emitter__=None,
        __event_call__=None,
    ) -> str:
        del __event_call__

        prompt = self._extract_prompt(body)
        is_enrichment = self._is_enrichment_prompt(prompt)
        raw_model_id = str(body.get("model", "agent_services.planner"))
        public_model = self._resolve_model(raw_model_id)
        agent_label = public_model.replace("-", " ").title()

        timeout = httpx.Timeout(
            connect=self.valves.CREATE_TIMEOUT_SECONDS,
            read=self.valves.STREAM_TIMEOUT_SECONDS,
            write=self.valves.CREATE_TIMEOUT_SECONDS,
            pool=self.valves.CREATE_TIMEOUT_SECONDS,
        )

        async with httpx.AsyncClient(
            base_url=self.valves.AGENT_BASE_URL.rstrip("/"),
            timeout=timeout,
            verify=self.valves.VERIFY_TLS,
            headers={"Accept": "application/json"},
        ) as client:
            try:
                available_models = await self._list_models(client)
                if public_model not in available_models:
                    raise Exception(
                        f"Agent Services model '{public_model}' is not available. "
                        f"Available models: {', '.join(sorted(available_models)) or 'none'}"
                    )

                payload = {
                    "model": public_model,
                    "stream": False,
                    "messages": self._extract_history(body),
                    "metadata": self._build_metadata(body, __user__, prompt),
                }

                completion = await self._create_completion(client, payload)
                completion_text = self._extract_completion_text(completion)
                task = completion.get("task") or {}

                if not isinstance(task, dict) or not task.get("id"):
                    debug_block = ""
                    if self.valves.INCLUDE_DEBUG_BLOCK and not is_enrichment:
                        debug_block = f"\n\nModel: `{public_model}`"

                    return f"{completion_text or 'Completed.'}{debug_block}"

                task_id = str(task["id"])
                task_state = str(task.get("state") or "unknown")
                stream_url = str(
                    task.get("stream_url") or f"/api/agent-tasks/{task_id}/stream"
                )

                await self._emit_status(
                    __event_emitter__,
                    f"Response task created: {task_id}",
                    suppress=is_enrichment,
                )

                if task_state in {"completed", "deferred_until_reset"}:
                    await self._emit_status(
                        __event_emitter__,
                        "Response complete.",
                        done=True,
                        suppress=is_enrichment,
                    )
                    debug_block = ""
                    if self.valves.INCLUDE_DEBUG_BLOCK and not is_enrichment:
                        debug_block = (
                            f"\n\nModel: `{public_model}`"
                            f"\nTask ID: `{task_id}`"
                            f"\nTask State: `{task_state}`"
                            f"\nStream URL: `{stream_url}`"
                        )
                    return f"{completion_text or 'Completed.'}{debug_block}"

                terminal_status = await self._stream_task(
                    client,
                    stream_url,
                    __event_emitter__,
                    suppress_status=is_enrichment,
                    agent_label=agent_label,
                )

                task_read = await self._read_task(client, task_id)
                final_state = str(
                    task_read.get("state") or terminal_status or task_state
                )
                summary = task_read.get("summary")
                approval_pending = bool(task_read.get("approval_pending"))
                links = task_read.get("links") or {}

                if final_state in {"completed", "deferred_until_reset"} and isinstance(
                    summary, str
                ) and summary.strip():
                    await self._emit_status(
                        __event_emitter__,
                        "Response complete.",
                        done=True,
                        suppress=is_enrichment,
                    )
                    debug_block = ""
                    if self.valves.INCLUDE_DEBUG_BLOCK and not is_enrichment:
                        debug_block = (
                            f"\n\nModel: `{public_model}`"
                            f"\nTask ID: `{task_id}`"
                            f"\nTask State: `{final_state}`"
                            f"\nStream URL: `{links.get('stream_url') or stream_url}`"
                        )

                    return f"{summary.strip()}{debug_block}"

                if approval_pending or final_state == "pending_approval":
                    await self._emit_status(
                        __event_emitter__,
                        "Approval required. Follow the task links to continue.",
                        done=True,
                        suppress=is_enrichment,
                    )

                    message = (
                        completion_text
                        or "Task accepted but requires approval before execution can continue."
                    )
                    debug_block = ""
                    if self.valves.INCLUDE_DEBUG_BLOCK and not is_enrichment:
                        debug_block = "\n\n" + self._task_block(
                            {
                                "id": task_id,
                                "state": final_state,
                                "stream_url": links.get("stream_url") or stream_url,
                                "approve_url": links.get("approve_url"),
                                "reject_url": links.get("reject_url"),
                            }
                        )

                    return f"{message}{debug_block}"

                if final_state == "rejected":
                    await self._emit_status(
                        __event_emitter__,
                        "Task was rejected.",
                        done=True,
                        suppress=is_enrichment,
                    )

                    debug_block = ""
                    if self.valves.INCLUDE_DEBUG_BLOCK and not is_enrichment:
                        debug_block = "\n\n" + self._task_block(
                            {
                                "id": task_id,
                                "state": final_state,
                                "stream_url": links.get("stream_url") or stream_url,
                                "approve_url": links.get("approve_url"),
                                "reject_url": links.get("reject_url"),
                            }
                        )

                    return f"Task was rejected before execution completed.{debug_block}"

                if final_state == "failed":
                    await self._emit_status(
                        __event_emitter__,
                        "Task failed.",
                        done=True,
                        suppress=is_enrichment,
                    )
                    raise Exception("Agent Services task failed.")

                message = (
                    completion_text
                    or "Task accepted. Follow the task stream for progress."
                )
                await self._emit_status(
                    __event_emitter__,
                    "Response complete.",
                    done=True,
                    suppress=is_enrichment,
                )
                debug_block = ""
                if self.valves.INCLUDE_DEBUG_BLOCK and not is_enrichment:
                    debug_block = "\n\n" + self._task_block(
                        {
                            "id": task_id,
                            "state": final_state,
                            "stream_url": links.get("stream_url") or stream_url,
                            "approve_url": links.get("approve_url"),
                            "reject_url": links.get("reject_url"),
                        }
                    )

                return f"{message}{debug_block}"

            except httpx.HTTPStatusError as exc:
                detail = exc.response.text.strip()
                message = f"Agent Services request failed: {exc.response.status_code}"
                if detail:
                    message = f"{message} - {detail}"
                await self._emit_notification(__event_emitter__, message, level="error")
                raise Exception(message) from exc

            except httpx.HTTPError as exc:
                message = f"Agent Services network error: {str(exc)}"
                await self._emit_notification(__event_emitter__, message, level="error")
                raise Exception(message) from exc
