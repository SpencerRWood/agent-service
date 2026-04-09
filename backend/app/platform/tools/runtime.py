from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from app.features.orchestration.schemas import (
    ApprovedWorkPackage,
    KnowledgeCaptureArtifact,
    WorkerExecutionResult,
)
from app.integrations.providers.base import ProviderExecutionError
from app.integrations.providers.router import PolicyBasedProviderRouter, ProviderRoutingError
from app.integrations.rag.client import RagIngestionClient, RagIngestionError, RagIngestionReceipt
from app.platform.execution_targets.dispatcher import (
    NullRemoteExecutionDispatcher,
    RemoteExecutionDispatcher,
)


class ToolExecutionError(RuntimeError):
    """Raised when a canonical platform tool cannot be executed."""


class ToolHandler(Protocol):
    async def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...


class PullRequestStateReader(Protocol):
    async def get_pull_request_state(
        self,
        *,
        repo: str,
        pr_number: int,
    ) -> Any: ...


class AgentExecuteCodingTaskHandler:
    def __init__(
        self,
        provider_router: PolicyBasedProviderRouter,
        remote_dispatcher: RemoteExecutionDispatcher | NullRemoteExecutionDispatcher,
    ) -> None:
        self._provider_router = provider_router
        self._remote_dispatcher = remote_dispatcher

    async def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            work_package = ApprovedWorkPackage.model_validate(payload["work_package"])
        except KeyError as exc:
            raise ToolExecutionError("Missing work_package payload for agent execution.") from exc

        explicit_target_id = work_package.source_metadata.get("execution_target")
        remote_result = await self._remote_dispatcher.dispatch(
            tool_name="agent.execute_coding_task",
            payload={"work_package": work_package.model_dump(mode="json")},
            explicit_target_id=str(explicit_target_id) if explicit_target_id else None,
            routing_context={
                "prompt": work_package.instructions,
                "route_profile": work_package.source_metadata.get("route_profile"),
            },
        )
        if remote_result is not None:
            return remote_result

        provider_name = work_package.provider
        try:
            provider = self._provider_router.get_provider(provider_name)
            result = await provider.execute(work_package)
        except (ProviderExecutionError, ProviderRoutingError) as primary_exc:
            fallback_provider_name = self._provider_router.choose_fallback_name(provider_name)
            if fallback_provider_name is None:
                raise ToolExecutionError(str(primary_exc)) from primary_exc

            fallback_work_package = work_package.model_copy(
                update={"provider": fallback_provider_name}
            )
            try:
                fallback_provider = self._provider_router.get_provider(fallback_provider_name)
                result = await fallback_provider.execute(fallback_work_package)
            except (ProviderExecutionError, ProviderRoutingError) as fallback_exc:
                raise ToolExecutionError(
                    "Worker execution failed. "
                    f"Primary provider '{provider_name.value}': {primary_exc}. "
                    f"Fallback provider '{fallback_provider_name.value}': {fallback_exc}."
                ) from fallback_exc

            result = result.model_copy(
                update={
                    "known_risks": [
                        (
                            f"Primary provider '{provider_name.value}' failed and fallback "
                            f"provider '{fallback_provider_name.value}' handled execution."
                        ),
                        *result.known_risks,
                    ]
                }
            )

        return result.model_dump(mode="json")


class RagStageArtifactHandler:
    def __init__(self, rag_client: RagIngestionClient) -> None:
        self._rag_client = rag_client

    async def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        artifact = KnowledgeCaptureArtifact.model_validate(payload["artifact"])
        try:
            receipt = await self._rag_client.stage_provisional(artifact)
        except RagIngestionError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return receipt.model_dump(mode="json")


class RagPromoteArtifactHandler:
    def __init__(self, rag_client: RagIngestionClient) -> None:
        self._rag_client = rag_client

    async def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        artifact = KnowledgeCaptureArtifact.model_validate(payload["artifact"])
        try:
            receipt = await self._rag_client.promote(artifact)
        except RagIngestionError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return receipt.model_dump(mode="json")


class RagMarkArtifactStaleHandler:
    def __init__(self, rag_client: RagIngestionClient) -> None:
        self._rag_client = rag_client

    async def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        artifact = KnowledgeCaptureArtifact.model_validate(payload["artifact"])
        reason = str(payload["reason"])
        try:
            receipt = await self._rag_client.mark_stale(artifact, reason=reason)
        except RagIngestionError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return receipt.model_dump(mode="json")


class RepoGetPullRequestStateHandler:
    def __init__(self, pr_state_reader: PullRequestStateReader) -> None:
        self._pr_state_reader = pr_state_reader

    async def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            repo = str(payload["repo"])
            pr_number = int(payload["pr_number"])
        except KeyError as exc:
            raise ToolExecutionError(
                "Missing repo or pr_number payload for PR state lookup."
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError(
                "repo must be a string and pr_number must be an integer."
            ) from exc

        state = await self._pr_state_reader.get_pull_request_state(repo=repo, pr_number=pr_number)
        if state is None:
            raise ToolExecutionError("Pull request state is unavailable for the requested input.")
        return state.model_dump(mode="json")


class ToolRuntime:
    def __init__(self, handlers: Mapping[str, ToolHandler]) -> None:
        self._handlers = dict(handlers)

    @classmethod
    def from_dependencies(
        cls,
        *,
        provider_router: PolicyBasedProviderRouter,
        rag_client: RagIngestionClient,
        pr_state_reader: PullRequestStateReader,
        remote_dispatcher: RemoteExecutionDispatcher | NullRemoteExecutionDispatcher | None = None,
    ) -> ToolRuntime:
        return cls(
            handlers={
                "agent.execute_coding_task": AgentExecuteCodingTaskHandler(
                    provider_router,
                    remote_dispatcher or NullRemoteExecutionDispatcher(),
                ),
                "rag.stage_provisional_artifact": RagStageArtifactHandler(rag_client),
                "rag.promote_artifact": RagPromoteArtifactHandler(rag_client),
                "rag.mark_artifact_stale": RagMarkArtifactStaleHandler(rag_client),
                "repo.get_pull_request_state": RepoGetPullRequestStateHandler(pr_state_reader),
            }
        )

    async def execute(self, tool_name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            handler = self._handlers[tool_name]
        except KeyError as exc:
            raise ToolExecutionError(
                f"Tool '{tool_name}' is not registered for execution."
            ) from exc
        return await handler.execute(payload)


def parse_worker_execution_result(payload: Mapping[str, Any]) -> WorkerExecutionResult:
    return WorkerExecutionResult.model_validate(payload)


def parse_rag_receipt(payload: Mapping[str, Any]) -> RagIngestionReceipt:
    return RagIngestionReceipt.model_validate(payload)
