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
    codex_command: str,
    copilot_command: str,
) -> dict[str, ToolHandler]:
    from app.features.orchestration.schemas import ApprovedWorkPackage, KnowledgeCaptureArtifact
    from app.integrations.github.client import GitHubPullRequestStateClient
    from app.integrations.providers.codex import CodexProvider
    from app.integrations.providers.copilot_cli import CopilotCliProvider
    from app.integrations.providers.router import ProviderRoutingError
    from app.integrations.rag.client import HttpRagIngestionClient

    codex_provider = CodexProvider(command=codex_command)
    copilot_provider = CopilotCliProvider(command=copilot_command)
    rag_client = HttpRagIngestionClient.from_settings()
    pr_state_client = GitHubPullRequestStateClient.from_settings()

    async def execute_coding_task(payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            work_package = ApprovedWorkPackage.model_validate(payload["work_package"])
        except KeyError as exc:
            raise RuntimeError("Missing work_package payload for agent execution.") from exc

        provider_name = work_package.provider.value
        if provider_name == codex_provider.provider_name:
            provider = codex_provider
        elif provider_name == copilot_provider.provider_name:
            provider = copilot_provider
        else:
            raise ProviderRoutingError(f"Provider '{provider_name}' is not registered")

        result = await provider.execute(work_package)
        return result.model_dump(mode="json")

    async def stage_provisional_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
        artifact = KnowledgeCaptureArtifact.model_validate(payload["artifact"])
        receipt = await rag_client.stage_provisional(artifact)
        return receipt.model_dump(mode="json")

    async def promote_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
        artifact = KnowledgeCaptureArtifact.model_validate(payload["artifact"])
        receipt = await rag_client.promote(artifact)
        return receipt.model_dump(mode="json")

    async def mark_artifact_stale(payload: Mapping[str, Any]) -> dict[str, Any]:
        artifact = KnowledgeCaptureArtifact.model_validate(payload["artifact"])
        reason = str(payload["reason"])
        receipt = await rag_client.mark_stale(artifact, reason=reason)
        return receipt.model_dump(mode="json")

    async def get_pull_request_state(payload: Mapping[str, Any]) -> dict[str, Any]:
        repo = str(payload["repo"])
        pr_number = int(payload["pr_number"])
        state = await pr_state_client.get_pull_request_state(repo=repo, pr_number=pr_number)
        if state is None:
            raise RuntimeError("Pull request state is unavailable for the requested input.")
        return state.model_dump(mode="json")

    return {
        "agent.execute_coding_task": execute_coding_task,
        "rag.stage_provisional_artifact": stage_provisional_artifact,
        "rag.promote_artifact": promote_artifact,
        "rag.mark_artifact_stale": mark_artifact_stale,
        "repo.get_pull_request_state": get_pull_request_state,
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
    parser.add_argument("--codex-command", default="codex")
    parser.add_argument("--copilot-command", default="copilot")
    parser.add_argument("--supported-tools", default="*")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--stdout-log-path", default="")
    parser.add_argument("--stderr-log-path", default="")
    args = parser.parse_args()

    handlers = build_tool_handlers(
        codex_command=args.codex_command,
        copilot_command=args.copilot_command,
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
