from app.core.agent_config import AgentProfile, AgentRegistry, ProviderAdapterConfig
from app.features.orchestration.schemas import ProviderName
from app.integrations.providers.router import PolicyBasedProviderRouter


def test_router_skips_disabled_provider():
    registry = AgentRegistry(
        agents={
            "worker_b": AgentProfile(
                display_name="Worker B",
                role="executor",
                default_provider=ProviderName.CODEX,
            )
        },
        providers={
            "codex": ProviderAdapterConfig(enabled=True, command="codex", dry_run=True),
            "copilot_cli": ProviderAdapterConfig(enabled=False, command="copilot", dry_run=True),
        },
    )

    router = PolicyBasedProviderRouter(
        default_provider="codex",
        repo_overrides={},
        fallback_enabled=True,
        providers={"codex": object()},
    )

    assert registry.get_provider("copilot_cli").enabled is False
    assert router.choose_fallback_name(ProviderName.CODEX) is None
