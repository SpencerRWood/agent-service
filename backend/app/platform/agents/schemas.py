from __future__ import annotations

from pydantic import BaseModel

from app.platform.agent_tasks.schemas import TaskClass


class AgentDefinition(BaseModel):
    id: str
    display_name: str
    description: str
    supports_streaming: bool = True
    requires_approval: bool = False
    runtime: str


class RuntimeDefinition(BaseModel):
    key: str
    task_class: TaskClass
    route_profile: str
    approval_mode: str = "none"
    prompt_preamble: str | None = None
