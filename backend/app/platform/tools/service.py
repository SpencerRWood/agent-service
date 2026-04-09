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
                "work_package": {"type": "object"},
            },
            "required": ["work_package"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "provider": {"type": "string"},
                "worker_target": {"type": "string"},
                "branch_name": {"type": "string"},
                "commit_shas": {"type": "array", "items": {"type": "string"}},
                "pr_title": {"type": "string"},
                "pr_body": {"type": "string"},
                "pr_url": {"type": "string"},
                "pr_number": {"type": "integer"},
                "execution_summary": {"type": "string"},
                "known_risks": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["provider", "branch_name", "pr_url", "pr_number", "execution_summary"],
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
        tool_name="rag.stage_provisional_artifact",
        display_name="Stage Provisional Artifact",
        description="Stage a provisional knowledge artifact in the RAG ingestion service.",
        version="2026-04-09",
        namespace="rag",
        input_schema={
            "type": "object",
            "properties": {
                "artifact": {"type": "object"},
            },
            "required": ["artifact"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "artifact_id": {"type": "string"},
                "operation": {"type": "string"},
                "remote_id": {"type": ["string", "null"]},
                "metadata": {"type": "object"},
            },
            "required": ["status", "artifact_id", "operation"],
        },
        side_effect={"class": "write", "destructive": False, "resource_types": ["knowledge_base"]},
        approval_policy={"mode": "conditional", "policy_key": "rag.ingest.write"},
        execution={"mode": "async", "timeout_seconds": 300, "idempotency_supported": True},
        observability={"emits_artifacts": True, "log_redaction_profile": "default"},
        availability={"enabled": True, "audiences": ["agent", "api"]},
    ),
    ToolDefinition(
        tool_name="rag.promote_artifact",
        display_name="Promote Artifact",
        description="Promote a provisional artifact after merge or final approval.",
        version="2026-04-09",
        namespace="rag",
        input_schema={
            "type": "object",
            "properties": {"artifact": {"type": "object"}},
            "required": ["artifact"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "artifact_id": {"type": "string"},
                "operation": {"type": "string"},
                "remote_id": {"type": ["string", "null"]},
                "metadata": {"type": "object"},
            },
            "required": ["status", "artifact_id", "operation"],
        },
        side_effect={"class": "write", "destructive": False, "resource_types": ["knowledge_base"]},
        approval_policy={"mode": "none"},
        execution={"mode": "async", "timeout_seconds": 120, "idempotency_supported": True},
        observability={"emits_artifacts": True, "log_redaction_profile": "default"},
        availability={"enabled": True, "audiences": ["agent", "api"]},
    ),
    ToolDefinition(
        tool_name="rag.mark_artifact_stale",
        display_name="Mark Artifact Stale",
        description="Mark a knowledge artifact stale after review regression or closure.",
        version="2026-04-09",
        namespace="rag",
        input_schema={
            "type": "object",
            "properties": {"artifact": {"type": "object"}, "reason": {"type": "string"}},
            "required": ["artifact", "reason"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "artifact_id": {"type": "string"},
                "operation": {"type": "string"},
                "remote_id": {"type": ["string", "null"]},
                "metadata": {"type": "object"},
            },
            "required": ["status", "artifact_id", "operation"],
        },
        side_effect={"class": "write", "destructive": False, "resource_types": ["knowledge_base"]},
        approval_policy={"mode": "none"},
        execution={"mode": "async", "timeout_seconds": 120, "idempotency_supported": True},
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
