#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

ToolHandler = Callable[[Mapping[str, Any]], Awaitable[dict[str, Any]]]


def build_tool_handlers(
    *,
    server_base_url: str,
    opencode_command: str,
) -> dict[str, ToolHandler]:
    from app.platform.agent_tasks.runtime import OpenCodeRuntime
    from app.platform.agent_tasks.schemas import AgentTaskEnvelope, TaskArtifact, TaskState

    opencode_runtime = OpenCodeRuntime.from_settings(opencode_command=opencode_command)

    class HttpTaskProgressReporter:
        def __init__(self, client: httpx.AsyncClient, envelope: AgentTaskEnvelope) -> None:
            self._client = client
            self._envelope = envelope

        async def publish(
            self,
            event_type: str,
            message: str,
            payload: dict | None = None,
        ) -> None:
            response = await self._client.post(
                f"/api/worker/agent-tasks/{self._envelope.task_id}/progress",
                json={
                    "run_id": self._envelope.run_id,
                    "step_id": self._envelope.step_id,
                    "correlation_id": self._envelope.correlation_id,
                    "state": payload.get("state") if payload else None,
                    "event_type": event_type,
                    "message": message,
                    "payload": payload or {},
                    "actor_type": "worker",
                    "actor_id": "worker-node",
                },
            )
            response.raise_for_status()

        async def publish_artifact(self, artifact: TaskArtifact) -> None:
            response = await self._client.post(
                f"/api/worker/agent-tasks/{self._envelope.task_id}/artifacts",
                json={
                    "run_id": self._envelope.run_id,
                    "run_step_id": self._envelope.step_id,
                    "artifact_type": artifact.artifact_type,
                    "title": artifact.title,
                    "content": artifact.content,
                    "uri": artifact.uri,
                    "provenance": artifact.provenance,
                    "status": artifact.status,
                },
            )
            response.raise_for_status()

    async def run_agent_task(payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            envelope = AgentTaskEnvelope.model_validate(payload["task"])
        except KeyError as exc:
            raise RuntimeError("Missing task payload for agent task execution.") from exc
        async with httpx.AsyncClient(base_url=server_base_url.rstrip("/"), timeout=60.0) as client:
            reporter = HttpTaskProgressReporter(client, envelope)
            await reporter.publish(
                "agent.task.worker.claimed",
                f"Worker claimed {envelope.task_class.value}.",
                {
                    "state": TaskState.QUEUED.value,
                    "worker_id": socket.gethostname(),
                    "preferred_backend": envelope.preferred_backend.value
                    if envelope.preferred_backend is not None
                    else None,
                },
            )
            result = await opencode_runtime.execute(envelope, reporter)
            for artifact in result.artifacts:
                await reporter.publish_artifact(artifact)
            await reporter.publish(
                "agent.task.finished",
                result.summary,
                {
                    "state": result.state.value,
                    "backend": result.backend.value if result.backend is not None else None,
                    "model": result.metrics.get("model"),
                    "reason_code": result.reason_code,
                    "retry_after": (
                        result.retry_after.isoformat() if result.retry_after is not None else None
                    ),
                },
            )
            return result.model_dump(mode="json")

    return {
        "agent.run_task": run_agent_task,
    }


def resolve_supported_tools(raw_value: str, handlers: Mapping[str, ToolHandler]) -> list[str]:
    normalized = raw_value.strip()
    if not normalized or normalized in {"*", "all"}:
        return list(handlers)
    return [tool.strip() for tool in normalized.split(",") if tool.strip()]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run a lightweight remote worker agent.")
    parser.add_argument("--server-base-url", required=True)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--worker-token", required=True)
    parser.add_argument("--opencode-command", default="opencode")
    parser.add_argument("--supported-tools", default="*")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--stdout-log-path", default="")
    parser.add_argument("--stderr-log-path", default="")
    args = parser.parse_args()

    handlers = build_tool_handlers(
        server_base_url=args.server_base_url,
        opencode_command=args.opencode_command,
    )
    supported_tools = resolve_supported_tools(args.supported_tools, handlers)

    headers = {"X-Worker-Token": args.worker_token}
    async with httpx.AsyncClient(base_url=args.server_base_url.rstrip("/"), timeout=60.0) as client:
        while True:
            await client.post(
                f"/api/worker/execution-targets/{args.target_id}/heartbeat",
                headers=headers,
                json={
                    "worker_id": args.worker_id,
                    "metadata": {
                        "runner": "worker_agent",
                        "hostname": socket.gethostname(),
                        "cwd": os.getcwd(),
                        "stdout_log_path": args.stdout_log_path,
                        "stderr_log_path": args.stderr_log_path,
                        "supported_tools": supported_tools,
                    },
                },
            )
            claim_response = await client.post(
                f"/api/worker/execution-targets/{args.target_id}/jobs/claim",
                headers=headers,
                json={
                    "worker_id": args.worker_id,
                    "supported_tools": supported_tools,
                },
            )
            claim_response.raise_for_status()
            job = claim_response.json().get("job")
            if not job:
                await asyncio.sleep(args.poll_interval)
                continue

            try:
                tool_name = str(job["tool_name"])
                payload = job["payload_json"]
                try:
                    handler = handlers[tool_name]
                except KeyError as exc:
                    raise RuntimeError(f"Worker does not support tool '{tool_name}'.") from exc

                result = await handler(payload)
                if result.get("state") == "deferred_until_reset":
                    task = payload.get("task", {})
                    deferred_response = await client.post(
                        f"/api/worker/agent-tasks/{task.get('task_id')}/deferred",
                        json={
                            "available_at": result.get("retry_after"),
                            "reason_code": result.get("reason_code"),
                            "backend": result.get("backend"),
                        },
                    )
                    deferred_response.raise_for_status()
                    requeue_response = await client.post(
                        f"/api/worker/execution-targets/{args.target_id}/jobs/{job['id']}/requeue",
                        headers=headers,
                        json={
                            "worker_id": args.worker_id,
                            "payload": payload,
                            "available_at": result.get("retry_after"),
                            "reason": {
                                "reason_code": result.get("reason_code"),
                                "backend": result.get("backend"),
                            },
                        },
                    )
                    requeue_response.raise_for_status()
                    await asyncio.sleep(args.poll_interval)
                    continue
                complete_response = await client.post(
                    f"/api/worker/execution-targets/{args.target_id}/jobs/{job['id']}/complete",
                    headers=headers,
                    json={"worker_id": args.worker_id, "result": result},
                )
                complete_response.raise_for_status()
            except Exception as exc:  # pragma: no cover - local worker script
                fail_response = await client.post(
                    f"/api/worker/execution-targets/{args.target_id}/jobs/{job['id']}/fail",
                    headers=headers,
                    json={
                        "worker_id": args.worker_id,
                        "error": {"detail": str(exc)},
                    },
                )
                fail_response.raise_for_status()
                await asyncio.sleep(args.poll_interval)


if __name__ == "__main__":
    asyncio.run(main())
