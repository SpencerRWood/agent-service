from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


@dataclass
class CommandExecutionResult:
    exit_code: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    async def run(self, argv: list[str], *, stdin: str | None = None) -> CommandExecutionResult: ...


class SubprocessCommandRunner:
    async def run(self, argv: list[str], *, stdin: str | None = None) -> CommandExecutionResult:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(stdin.encode() if stdin is not None else None)
        return CommandExecutionResult(
            exit_code=process.returncode or 0,
            stdout=stdout.decode(),
            stderr=stderr.decode(),
        )
