from __future__ import annotations

from fastapi import HTTPException, status

from app.platform.agents.catalog import load_agent_catalog
from app.platform.agents.schemas import AgentDefinition, RuntimeDefinition


class AgentRegistry:
    def __init__(
        self,
        runtime_registry: RuntimeRegistry,
        agents: list[AgentDefinition] | None = None,
    ) -> None:
        if agents is None:
            agents = load_agent_catalog().agents
        self._runtime_registry = runtime_registry
        self._agents = {agent.id: agent.model_copy(deep=True) for agent in agents}
        for agent in self._agents.values():
            runtime = self._runtime_registry.get_runtime(agent.runtime)
            agent.requires_approval = runtime.approval_mode != "none"

    def list_agents(self) -> list[AgentDefinition]:
        return list(self._agents.values())

    def get_agent(self, agent_id: str) -> AgentDefinition:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown agent '{agent_id}'.",
            )
        return agent


class RuntimeRegistry:
    def __init__(self, runtimes: list[RuntimeDefinition] | None = None) -> None:
        if runtimes is None:
            runtimes = load_agent_catalog().runtimes
        self._runtimes = {runtime.key: runtime.model_copy(deep=True) for runtime in runtimes}

    def get_runtime(self, runtime_key: str) -> RuntimeDefinition:
        runtime = self._runtimes.get(runtime_key)
        if runtime is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown runtime '{runtime_key}'.",
            )
        return runtime


def get_runtime_registry() -> RuntimeRegistry:
    catalog = load_agent_catalog()
    return RuntimeRegistry(catalog.runtimes)


def get_agent_registry() -> AgentRegistry:
    catalog = load_agent_catalog()
    runtime_registry = RuntimeRegistry(catalog.runtimes)
    return AgentRegistry(runtime_registry, catalog.agents)
