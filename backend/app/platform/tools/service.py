from fastapi import HTTPException, status

from app.platform.tools.schemas import ToolDefinition

BUILTIN_TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        tool_name="agent.run_task",
        display_name="Run Agent Task",
        description="Run a structured brokered agent task on a worker node.",
        version="2026-04-10",
        namespace="agent",
        input_schema={
            "type": "object",
            "properties": {
                "task": {"type": "object"},
            },
            "required": ["task"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "backend": {"type": "string"},
                "execution_path": {"type": "string"},
                "summary": {"type": "string"},
                "raw_output": {"type": "object"},
                "artifacts": {"type": "array"},
                "metrics": {"type": "object"},
            },
            "required": ["status", "backend", "execution_path", "summary"],
        },
        side_effect={"class": "write", "destructive": False, "resource_types": ["repository"]},
        approval_policy={
            "mode": "required",
            "policy_key": "agent.run.write",
            "approval_scope": "per_invocation",
        },
        execution={"mode": "async", "timeout_seconds": 900, "idempotency_supported": False},
        observability={"emits_artifacts": True, "log_redaction_profile": "default"},
        availability={"enabled": True, "audiences": ["agent", "api", "chat"]},
    ),
]


class ToolRegistryService:
    def list_tools(self) -> list[ToolDefinition]:
        return BUILTIN_TOOLS

    def get_tool(self, tool_name: str) -> ToolDefinition:
        for tool in BUILTIN_TOOLS:
            if tool.tool_name == tool_name:
                return tool
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
