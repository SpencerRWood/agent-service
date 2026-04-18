from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PullRequestStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    DISMISSED = "dismissed"
    MERGED = "merged"
    CLOSED = "closed"


class PullRequestState(BaseModel):
    status: PullRequestStatus
    approved_by: list[str] = Field(default_factory=list)
    merged_at: datetime | None = None
    source: str = "event"


class ProjectContext(BaseModel):
    project_id: str | None = None
    project_slug: str | None = None
    project_path: str | None = None


class ExecutorWorkPackage(BaseModel):
    run_id: str
    backend: str
    repo: str
    runtime_key: str | None = None
    public_agent_id: str | None = None
    agent_system_prompt: str | None = None
    project: ProjectContext | None = None
    branch_strategy: str
    instructions: str
    constraints: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    workflow: dict[str, Any] = Field(default_factory=dict)
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutorResult(BaseModel):
    provider: str
    branch_name: str
    commit_shas: list[str]
    pr_title: str
    pr_body: str
    pr_url: str
    pr_number: int
    execution_summary: str
    known_risks: list[str] = Field(default_factory=list)


class ArtifactStage(StrEnum):
    PROVISIONAL = "provisional"
    PROMOTED = "promoted"
    STALE = "stale"


class ArtifactFile(BaseModel):
    path: str
    media_type: str
    title: str
    content: str
    sha256: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_content(
        cls,
        *,
        path: str,
        media_type: str,
        title: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactFile:
        from hashlib import sha256

        return cls(
            path=path,
            media_type=media_type,
            title=title,
            content=content,
            sha256=sha256(content.encode("utf-8")).hexdigest(),
            metadata=metadata or {},
        )


class ArtifactManifest(BaseModel):
    artifact_id: str
    repo: str
    project: ProjectContext | None = None
    provider: str
    stage: ArtifactStage
    generated_at: datetime
    source_run_id: str
    source_pr_url: str
    source_pr_number: int | None = None
    tags: list[str] = Field(default_factory=list)


class KnowledgeCaptureArtifact(BaseModel):
    manifest: ArtifactManifest
    implementation_summary: str
    operational_notes: list[str]
    decision_log: list[str]
    knowledge_chunks: list[str]
    documents: list[ArtifactFile] = Field(default_factory=list)
    promotion_history: list[dict[str, Any]] = Field(default_factory=list)
    source_pr_url: str
    provisional: bool = True
