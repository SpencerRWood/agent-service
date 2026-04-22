#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import re
import sys
from typing import Any
from uuid import uuid4

import httpx
from openwebui_pipe import Pipe

BASE_URL = os.environ.get("AGENT_BASE_URL", "https://agents.woodhost.cloud").rstrip("/")
WORKER_TARGET_ID = os.environ.get("WORKER_TARGET_ID", "").strip()
PROMPT = os.environ.get(
    "PIPE_E2E_PROMPT",
    "Give me a test plan for creating an agent.",
)
PROMPT_RUN_MARKER = os.environ.get("PIPE_E2E_RUN_MARKER", f"pipe-e2e-{uuid4()}")
STREAM_TIMEOUT_SECONDS = float(os.environ.get("STREAM_TIMEOUT_SECONDS", "900"))
CREATE_TIMEOUT_SECONDS = float(os.environ.get("CREATE_TIMEOUT_SECONDS", "30"))


def _api_url(path: str) -> str:
    return f"{BASE_URL}/api{path}"


async def _get_json(client: httpx.AsyncClient, path: str) -> Any:
    response = await client.get(_api_url(path))
    response.raise_for_status()
    return response.json()


async def _select_worker(client: httpx.AsyncClient) -> str | None:
    targets = await _get_json(client, "/admin/execution-targets/")
    candidates = [
        target
        for target in targets
        if target.get("enabled") is True
        and "agent.run_task" in (target.get("supported_tools_json") or [])
    ]
    if WORKER_TARGET_ID:
        candidates = [target for target in candidates if target.get("id") == WORKER_TARGET_ID]
    if not candidates:
        return None
    candidates.sort(key=lambda target: bool(target.get("is_default")), reverse=True)
    selected = candidates[0]
    target_id = str(selected["id"])
    health = await _get_json(client, f"/admin/execution-targets/{target_id}/health")
    if health.get("online") is not True:
        raise AssertionError(f"Worker target {target_id!r} exists but is not online: {health}")
    return target_id


def _extract_task_id(output: str) -> str:
    match = re.search(r"Task ID:\s*`([^`]+)`", output)
    if not match:
        raise AssertionError(f"Pipe output did not include a task id:\n{output}")
    return match.group(1)


async def _collect_stream_events(client: httpx.AsyncClient, task_id: str) -> tuple[list[str], str]:
    events: list[str] = []
    terminal_status = "unknown"
    current_event = ""
    async with client.stream(
        "GET",
        _api_url(f"/agent-tasks/{task_id}/stream"),
        timeout=STREAM_TIMEOUT_SECONDS,
    ) as response:
        response.raise_for_status()
        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("event: "):
                current_event = line[len("event: ") :]
                continue
            if not line.startswith("data: "):
                continue
            events.append(f"{current_event}: {line[len('data: '):]}")
            if current_event == "terminal":
                terminal_status_match = re.search(r'"status"\s*:\s*"([^"]+)"', line)
                if terminal_status_match:
                    terminal_status = terminal_status_match.group(1)
                break
    return events, terminal_status


async def main() -> int:
    async with httpx.AsyncClient(timeout=CREATE_TIMEOUT_SECONDS) as client:
        selected_worker = await _select_worker(client)
        if selected_worker is None:
            print(
                "[SKIP] No enabled online worker target supports agent.run_task; "
                "OpenWebUI pipe E2E test was not run."
            )
            return 0
        print(f"[PASS] Selected worker target {selected_worker!r}.")

    emitted_events: list[dict[str, Any]] = []

    async def event_emitter(event: dict[str, Any]) -> None:
        emitted_events.append(event)

    pipe = Pipe()
    pipe.valves.AGENT_BASE_URL = BASE_URL
    pipe.valves.CREATE_TIMEOUT_SECONDS = CREATE_TIMEOUT_SECONDS
    pipe.valves.STREAM_TIMEOUT_SECONDS = STREAM_TIMEOUT_SECONDS
    pipe.valves.INCLUDE_DEBUG_BLOCK = True
    pipe.valves.EMIT_RAW_STREAM_EVENTS = True

    body = {
        "model": "agent_services.planner",
        "stream": True,
        "messages": [
            {
                "role": "user",
                "content": f"{PROMPT}\n\nE2E run marker: {PROMPT_RUN_MARKER}",
            }
        ],
        "chat_id": "openwebui-pipe-e2e",
        "id": "openwebui-pipe-e2e-message",
    }

    output = await pipe.pipe(
        body,
        __user__={"id": "pipe-e2e", "name": "Pipe E2E", "role": "admin"},
        __event_emitter__=event_emitter,
    )

    if "No backend is currently available. Task deferred until reset." in output:
        raise AssertionError(f"Pipe returned the deferred-backend failure:\n{output}")
    if "Task State: `deferred_until_reset`" in output:
        raise AssertionError(f"Pipe returned deferred_until_reset:\n{output}")

    task_id = _extract_task_id(output)
    async with httpx.AsyncClient(timeout=CREATE_TIMEOUT_SECONDS) as client:
        task = await _get_json(client, f"/agent-tasks/{task_id}")
        stream_events, terminal_status = await _collect_stream_events(client, task_id)

    if task.get("state") != "completed":
        raise AssertionError(f"Expected completed task, got {task.get('state')}: {task}")
    if terminal_status != "completed":
        raise AssertionError(f"Expected completed terminal status, got {terminal_status}")
    if not any("agent.task.worker.claimed" in event for event in stream_events):
        raise AssertionError("Planner task stream did not include agent.task.worker.claimed.")
    if not any(selected_worker in event for event in stream_events):
        raise AssertionError(f"Planner task stream did not mention worker {selected_worker!r}.")

    print(f"[PASS] Pipe returned completed planner task {task_id}.")
    print("[PASS] Planner stream included worker claim and completed terminal event.")
    print(f"[INFO] Captured {len(emitted_events)} Open WebUI event emitter update(s).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
