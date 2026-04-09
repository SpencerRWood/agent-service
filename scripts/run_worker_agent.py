#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import socket

import httpx


async def run_command(command: str, stdin_payload: str) -> dict:
    argv = shlex.split(command)
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(stdin_payload.encode())
    if process.returncode != 0:
        raise RuntimeError(stderr.decode().strip() or stdout.decode().strip() or "command failed")
    payload = json.loads(stdout.decode())
    if not isinstance(payload, dict):
        raise RuntimeError("worker command returned a non-object JSON payload")
    return payload


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run a lightweight remote worker agent.")
    parser.add_argument("--server-base-url", required=True)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--worker-token", required=True)
    parser.add_argument("--codex-command", default="codex")
    parser.add_argument("--copilot-command", default="copilot")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--stdout-log-path", default="")
    parser.add_argument("--stderr-log-path", default="")
    args = parser.parse_args()

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
                    },
                },
            )
            claim_response = await client.post(
                f"/api/worker/execution-targets/{args.target_id}/jobs/claim",
                headers=headers,
                json={
                    "worker_id": args.worker_id,
                    "supported_tools": ["agent.execute_coding_task"],
                },
            )
            claim_response.raise_for_status()
            job = claim_response.json().get("job")
            if not job:
                await asyncio.sleep(args.poll_interval)
                continue

            try:
                payload = job["payload_json"]
                work_package = payload["work_package"]
                provider = work_package["provider"]
                command = args.codex_command if provider == "codex" else args.copilot_command
                result = await run_command(command, json.dumps(work_package))
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
