from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.features.orchestration.schemas import ProviderName, WorkerTarget


class ProviderAdapterConfig(BaseModel):
    enabled: bool = True
    command: str
    dry_run: bool = True


class AgentProfile(BaseModel):
    display_name: str
    role: str
    requested_by: str | None = None
    assigned_to: str | None = None
    worker_target: WorkerTarget | None = None
    default_provider: ProviderName | None = None
    instructions: str | None = None


class AgentRegistry(BaseModel):
    version: int = 1
    agents: dict[str, AgentProfile] = Field(default_factory=dict)
    providers: dict[str, ProviderAdapterConfig] = Field(default_factory=dict)

    def get_agent(self, agent_id: str) -> AgentProfile | None:
        return self.agents.get(agent_id)

    def get_provider(self, provider_name: str) -> ProviderAdapterConfig | None:
        return self.providers.get(provider_name)


def load_agent_registry(config_path: Path) -> AgentRegistry:
    if not config_path.exists():
        return AgentRegistry()

    raw = yaml.safe_load(config_path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("Agent config must contain a YAML object at the top level.")

    return AgentRegistry.model_validate(raw)
