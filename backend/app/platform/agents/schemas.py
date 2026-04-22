from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.platform.agent_tasks.schemas import BackendName, TaskClass


class AgentWorkflowActionDefinition(BaseModel):
    action: str
    to: str | None = None
    prompt: str | None = None


class AgentWorkflowStepDefinition(BaseModel):
    id: str
    title: str | None = None
    instructions: str
    run: str | None = None
    when: str | None = None
    output: str | None = None
    on_success: AgentWorkflowActionDefinition | None = None
    on_needs_changes: AgentWorkflowActionDefinition | None = None
    on_failure: AgentWorkflowActionDefinition | None = None


class AgentWorkflowDefinition(BaseModel):
    goal: str | None = None
    max_iterations: int = 1
    entry_step: str | None = None
    handoff_to: str | None = None
    handoff_summary_prompt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    steps: list[AgentWorkflowStepDefinition] = Field(default_factory=list)


class AgentDefinition(BaseModel):
    id: str
    display_name: str
    description: str
    supports_streaming: bool = True
    requires_approval: bool = False
    system_prompt: str | None = None
    workflow: AgentWorkflowDefinition | None = None
    runtime: str


class RuntimeDefinition(BaseModel):
    key: str
    task_class: TaskClass
    route_profile: str
    approval_mode: str = "none"
    prompt_preamble: str | None = None


class AgentCatalogDefinition(BaseModel):
    agents: list[AgentDefinition]
    runtimes: list[RuntimeDefinition]


class AgentCatalogConfigRead(BaseModel):
    default_path: str
    override_path: str
    has_override: bool
    default_yaml: str
    override_yaml: str | None = None
    effective_yaml: str
    default_catalog: dict[str, Any]
    override_catalog: dict[str, Any] | None = None
    effective_catalog: dict[str, Any]


class AgentCatalogOverrideUpdate(BaseModel):
    yaml: str = Field(default="")


class AgentCatalogStructuredUpdate(BaseModel):
    catalog: AgentCatalogDefinition


class BackendModelsConfigRead(BaseModel):
    default_models: dict[str, str] = Field(default_factory=dict)
    override_models: dict[str, str] | None = None
    effective_models: dict[str, str] = Field(default_factory=dict)


class BackendModelsUpdate(BaseModel):
    models: dict[BackendName, str] = Field(default_factory=dict)
