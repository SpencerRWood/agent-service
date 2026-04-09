from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.session import get_db
from app.features.orchestration.platform_bridge import SqlPlatformRecorder
from app.features.orchestration.repository import OrchestrationRunRepository
from app.features.orchestration.service import OrchestrationService
from app.integrations.control_hub.client import HttpControlHubClient
from app.integrations.github.client import GitHubPullRequestStateClient
from app.integrations.providers.router import PolicyBasedProviderRouter
from app.integrations.rag.client import HttpRagIngestionClient
from app.platform.execution_targets.dispatcher import RemoteExecutionDispatcher
from app.platform.execution_targets.repository import ExecutionTargetRepository
from app.platform.execution_targets.service import ExecutionTargetService


def get_orchestration_service(
    db: AsyncSession = Depends(get_db),
) -> OrchestrationService:
    repository = OrchestrationRunRepository(db)
    execution_target_service = ExecutionTargetService(ExecutionTargetRepository(db))
    return OrchestrationService(
        repository=repository,
        control_hub_client=HttpControlHubClient.from_settings(),
        provider_router=PolicyBasedProviderRouter.from_settings(),
        rag_client=HttpRagIngestionClient.from_settings(),
        pr_state_client=GitHubPullRequestStateClient.from_settings(),
        platform_recorder=SqlPlatformRecorder(db),
        remote_dispatcher=RemoteExecutionDispatcher(execution_target_service),
    )
