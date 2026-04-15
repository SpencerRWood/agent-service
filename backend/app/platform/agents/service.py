from __future__ import annotations

from fastapi import HTTPException, status

from app.platform.agent_tasks.schemas import TaskClass
from app.platform.agents.schemas import AgentDefinition, RuntimeDefinition


class AgentRegistry:
    def __init__(self, runtime_registry: RuntimeRegistry) -> None:
        self._runtime_registry = runtime_registry
        self._agents = {
            "planner": AgentDefinition(
                id="planner",
                display_name="Planner",
                description="Breaks work into clear steps, tradeoffs, and execution plans.",
                supports_streaming=True,
                runtime="planner_runtime",
            ),
            "rag-analyst": AgentDefinition(
                id="rag-analyst",
                display_name="RAG Analyst",
                description="Analyzes requests with retrieval-oriented runtime hints.",
                supports_streaming=True,
                runtime="rag_analysis_runtime",
            ),
            "coder": AgentDefinition(
                id="coder",
                display_name="Coder",
                description="Implements repository changes through the internal task runtime.",
                supports_streaming=True,
                runtime="coding_runtime",
            ),
            "reviewer": AgentDefinition(
                id="reviewer",
                display_name="Reviewer",
                description="Reviews changes with approval gating before execution continues.",
                supports_streaming=True,
                runtime="review_runtime",
            ),
        }
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
    def __init__(self) -> None:
        self._runtimes = {
            "planner_runtime": RuntimeDefinition(
                key="planner_runtime",
                task_class=TaskClass.PLAN_ONLY,
                route_profile="cheap",
                approval_mode="none",
                prompt_preamble="Focus on sequencing, assumptions, and clear next steps.",
            ),
            "rag_analysis_runtime": RuntimeDefinition(
                key="rag_analysis_runtime",
                task_class=TaskClass.ANALYZE,
                route_profile="cheap",
                approval_mode="none",
                prompt_preamble="Add retrieval-aware analysis and note where external knowledge would improve confidence.",
            ),
            "coding_runtime": RuntimeDefinition(
                key="coding_runtime",
                task_class=TaskClass.IMPLEMENT,
                route_profile="implementation",
                approval_mode="none",
                prompt_preamble="Prefer direct repository changes, preserving existing patterns and testing the result.",
            ),
            "review_runtime": RuntimeDefinition(
                key="review_runtime",
                task_class=TaskClass.REVIEW,
                route_profile="implementation",
                approval_mode="required",
                prompt_preamble="Prioritize correctness risks, regressions, and missing tests before summaries.",
            ),
        }

    def get_runtime(self, runtime_key: str) -> RuntimeDefinition:
        runtime = self._runtimes.get(runtime_key)
        if runtime is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown runtime '{runtime_key}'.",
            )
        return runtime


def get_runtime_registry() -> RuntimeRegistry:
    return RuntimeRegistry()


def get_agent_registry() -> AgentRegistry:
    return AgentRegistry(get_runtime_registry())
