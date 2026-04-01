from __future__ import annotations

from typing import Protocol

from app.features.orchestration.schemas import ApprovedWorkPackage, WorkerExecutionResult


class ProviderExecutionError(RuntimeError):
    """Raised when a worker provider cannot execute a work package."""


class WorkerProvider(Protocol):
    provider_name: str

    async def execute(self, work_package: ApprovedWorkPackage) -> WorkerExecutionResult: ...
