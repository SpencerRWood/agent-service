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
        runner = SubprocessCommandRunner()
        providers: dict[str, WorkerProvider] = {
            "codex": CodexProvider(command=settings.codex_command, runner=runner),
            "copilot_cli": CopilotCliProvider(
                command=settings.copilot_cli_command,
                runner=runner,
            ),
        }
        return cls(
            default_provider=settings.orchestration_default_provider,
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
