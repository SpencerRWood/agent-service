from fastapi import HTTPException, status

from app.platform.tools.schemas import ToolDefinition

BUILTIN_TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        tool_name="agent.execute_coding_task",
        display_name="Execute Coding Task",
        description="Run a bounded coding task through an external agent runtime.",
        version="2026-04-09",
        namespace="agent",
        input_schema={
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "repo": {"type": "string"},
                "constraints": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "artifacts": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["summary"],
        },
        side_effect={"class": "write", "destructive": False, "resource_types": ["repository"]},
        approval_policy={
            "mode": "required",
            "policy_key": "agent.execute.write",
            "approval_scope": "per_invocation",
        },
        execution={"mode": "async", "timeout_seconds": 900, "idempotency_supported": False},
        observability={"emits_artifacts": True, "log_redaction_profile": "default"},
        availability={"enabled": True, "audiences": ["agent", "api", "chat"]},
    ),
    ToolDefinition(
        tool_name="rag.ingest_documents",
        display_name="Ingest Documents",
        description="Send structured documents to the RAG ingestion service.",
        version="2026-04-09",
        namespace="rag",
        input_schema={
            "type": "object",
            "properties": {
                "documents": {"type": "array", "items": {"type": "object"}},
                "project": {"type": "string"},
            },
            "required": ["documents"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}, "document_count": {"type": "integer"}},
            "required": ["status"],
        },
        side_effect={"class": "write", "destructive": False, "resource_types": ["knowledge_base"]},
        approval_policy={"mode": "conditional", "policy_key": "rag.ingest.write"},
        execution={"mode": "async", "timeout_seconds": 300, "idempotency_supported": True},
        observability={"emits_artifacts": True, "log_redaction_profile": "default"},
        availability={"enabled": True, "audiences": ["agent", "api"]},
    ),
    ToolDefinition(
        tool_name="repo.get_pull_request_state",
        display_name="Get Pull Request State",
        description="Read pull request state from the git provider.",
        version="2026-04-09",
        namespace="repo",
        input_schema={
            "type": "object",
            "properties": {"repo": {"type": "string"}, "pr_number": {"type": "integer"}},
            "required": ["repo", "pr_number"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}, "approved_by": {"type": "array"}},
            "required": ["status"],
        },
        side_effect={"class": "read", "destructive": False, "resource_types": ["pull_request"]},
        approval_policy={"mode": "none"},
        execution={"mode": "sync", "timeout_seconds": 30, "idempotency_supported": True},
        observability={"emits_artifacts": False, "log_redaction_profile": "default"},
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
