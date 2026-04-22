from __future__ import annotations

from app.core.settings import settings


def build_task_action_url(task_id: str, action: str) -> str:
    path = f"/api/agent-tasks/{task_id}/{action}"
    base_url = (settings.agent_services_base_url or "").rstrip("/")
    return f"{base_url}{path}" if base_url else path
