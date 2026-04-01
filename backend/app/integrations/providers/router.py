from __future__ import annotations

from collections.abc import Mapping

from app.core.settings import settings
from app.features.orchestration.schemas import ExecutionProposal, ProviderName
from app.integrations.providers.base import WorkerProvider
from app.integrations.providers.codex import CodexProvider
from app.integrations.providers.copilot_cli import CopilotCliProvider
from app.integrations.providers.runner import SubprocessCommandRunner


class ProviderRoutingError(RuntimeError):
    """Raised when no execution provider can be selected for a run."""


class PolicyBasedProviderRouter:
    def __init__(
        self,
        *,
        default_provider: str,
        repo_overrides: Mapping[str, str],
        fallback_enabled: bool,
        providers: Mapping[str, WorkerProvider],
    ) -> None:
        self._default_provider = default_provider
        self._repo_overrides = dict(repo_overrides)
        self._fallback_enabled = fallback_enabled
        self._providers = dict(providers)

    @classmethod
    def from_settings(cls) -> PolicyBasedProviderRouter:
        registry = settings.agent_registry
        runner = SubprocessCommandRunner()
        codex_provider_config = registry.get_provider("codex")
        copilot_provider_config = registry.get_provider("copilot_cli")
        worker_b_profile = registry.get_agent("worker_b")
        providers: dict[str, WorkerProvider] = {}

        if codex_provider_config is None or codex_provider_config.enabled:
            providers["codex"] = CodexProvider(
                command=(
                    codex_provider_config.command
                    if codex_provider_config is not None
                    else settings.codex_command
                ),
                dry_run=(
                    codex_provider_config.dry_run
                    if codex_provider_config is not None
                    else settings.orchestration_dry_run
                ),
                runner=runner,
            )

        if copilot_provider_config is None or copilot_provider_config.enabled:
            providers["copilot_cli"] = CopilotCliProvider(
                command=(
                    copilot_provider_config.command
                    if copilot_provider_config is not None
                    else settings.copilot_cli_command
                ),
                dry_run=(
                    copilot_provider_config.dry_run
                    if copilot_provider_config is not None
                    else settings.orchestration_dry_run
                ),
                runner=runner,
            )
        return cls(
            default_provider=(
                worker_b_profile.default_provider.value
                if worker_b_profile is not None and worker_b_profile.default_provider is not None
                else settings.orchestration_default_provider
            ),
            repo_overrides=settings.orchestration_provider_repo_overrides,
            fallback_enabled=settings.orchestration_provider_fallback_enabled,
            providers=providers,
        )

    def choose_provider_name(self, proposal: ExecutionProposal) -> ProviderName:
        candidate = self._repo_overrides.get(proposal.repo, proposal.recommended_provider)
        if candidate not in self._providers:
            candidate = self._default_provider
        if candidate not in self._providers:
            raise ProviderRoutingError(
                f"No provider is configured for repo '{proposal.repo}' or default '{candidate}'."
            )
        return ProviderName(candidate)

    def get_provider(self, provider_name: ProviderName) -> WorkerProvider:
        try:
            return self._providers[provider_name.value]
        except KeyError as exc:
            raise ProviderRoutingError(f"Provider '{provider_name}' is not registered") from exc

    def choose_fallback_name(self, failed_provider_name: ProviderName) -> ProviderName | None:
        if not self._fallback_enabled:
            return None

        if (
            self._default_provider in self._providers
            and self._default_provider != failed_provider_name.value
        ):
            return ProviderName(self._default_provider)

        for provider_name in self._providers:
            if provider_name != failed_provider_name.value:
                return ProviderName(provider_name)

        return None
