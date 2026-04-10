from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.settings import settings
from app.platform.agent_tasks.contracts import KnowledgeCaptureArtifact

logger = get_logger(__name__)


class RagIngestionError(RuntimeError):
    """Raised when the RAG ingestion service cannot process an artifact request."""


class RagIngestionReceipt(BaseModel):
    status: str
    artifact_id: str
    operation: str
    remote_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RagIngestionClient(Protocol):
    async def stage_provisional(
        self, artifact: KnowledgeCaptureArtifact
    ) -> RagIngestionReceipt: ...

    async def promote(self, artifact: KnowledgeCaptureArtifact) -> RagIngestionReceipt: ...

    async def mark_stale(
        self,
        artifact: KnowledgeCaptureArtifact,
        *,
        reason: str,
    ) -> RagIngestionReceipt: ...


class NoOpRagIngestionClient:
    async def stage_provisional(self, artifact: KnowledgeCaptureArtifact) -> RagIngestionReceipt:
        return self._build_receipt(artifact, operation="stage_provisional", status="noop")

    async def promote(self, artifact: KnowledgeCaptureArtifact) -> RagIngestionReceipt:
        return self._build_receipt(artifact, operation="promote", status="noop")

    async def mark_stale(
        self,
        artifact: KnowledgeCaptureArtifact,
        *,
        reason: str,
    ) -> RagIngestionReceipt:
        return self._build_receipt(
            artifact,
            operation="mark_stale",
            status="noop",
            metadata={"reason": reason},
        )

    def _build_receipt(
        self,
        artifact: KnowledgeCaptureArtifact,
        *,
        operation: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> RagIngestionReceipt:
        return RagIngestionReceipt(
            status=status,
            artifact_id=artifact.manifest.artifact_id,
            operation=operation,
            remote_id=artifact.manifest.artifact_id,
            metadata=metadata or {},
        )


class HttpRagIngestionClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client

    @classmethod
    def from_settings(cls) -> RagIngestionClient:
        if not settings.rag_ingestion_enabled:
            return NoOpRagIngestionClient()

        return cls(
            base_url=settings.rag_ingestion_base_url,
            timeout_seconds=settings.rag_ingestion_timeout_seconds,
        )

    async def stage_provisional(self, artifact: KnowledgeCaptureArtifact) -> RagIngestionReceipt:
        ingest_results: list[dict[str, Any]] = []
        for document in artifact.documents:
            payload = await self._request(
                "POST",
                "/ingest/text",
                json={
                    "text": document.content,
                    "title": document.title,
                    "external_id": artifact.manifest.artifact_id,
                    "source_name": artifact.manifest.provider,
                    "content_type": document.media_type,
                    "tags": artifact.manifest.tags,
                    "project": self._project_value(artifact),
                    "metadata": {
                        "manifest": artifact.manifest.model_dump(mode="json"),
                        "document": {
                            "path": document.path,
                            "title": document.title,
                            "sha256": document.sha256,
                            "metadata": document.metadata,
                        },
                        "implementation_summary": artifact.implementation_summary,
                        "operational_notes": artifact.operational_notes,
                        "decision_log": artifact.decision_log,
                        "promotion_history": artifact.promotion_history,
                        "provisional": artifact.provisional,
                    },
                },
            )
            ingest_results.append(payload)

        return RagIngestionReceipt(
            status="indexed",
            artifact_id=artifact.manifest.artifact_id,
            operation="stage_provisional",
            remote_id=ingest_results[0]["document_id"] if ingest_results else None,
            metadata={
                "documents": ingest_results,
                "document_count": len(ingest_results),
            },
        )

    async def promote(self, artifact: KnowledgeCaptureArtifact) -> RagIngestionReceipt:
        return RagIngestionReceipt(
            status="local_only",
            artifact_id=artifact.manifest.artifact_id,
            operation="promote",
            remote_id=None,
            metadata={"reason": "Remote promote route is not implemented in the RAG service."},
        )

    async def mark_stale(
        self,
        artifact: KnowledgeCaptureArtifact,
        *,
        reason: str,
    ) -> RagIngestionReceipt:
        return RagIngestionReceipt(
            status="local_only",
            artifact_id=artifact.manifest.artifact_id,
            operation="mark_stale",
            remote_id=None,
            metadata={
                "reason": reason,
                "detail": "Remote stale route is not implemented in the RAG service.",
            },
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
    ) -> Any:
        logger.info(
            "Sending RAG ingestion request",
            extra={
                "event": "rag_request_started",
                "integration": "rag_ingestion",
                "http": {"method": method, "path": path},
            },
        )
        if self._client is not None:
            response = await self._client.request(method, path, json=json)
        else:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.request(method, path, json=json)

        if response.status_code == 422:
            logger.warning(
                "RAG ingestion validation error",
                extra={
                    "event": "rag_validation_error",
                    "integration": "rag_ingestion",
                    "http": {"method": method, "path": path, "status_code": response.status_code},
                },
            )
            raise RagIngestionError(f"RAG ingestion validation error: {response.text}")

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "RAG ingestion request failed",
                extra={
                    "event": "rag_request_failed",
                    "integration": "rag_ingestion",
                    "http": {
                        "method": method,
                        "path": path,
                        "status_code": exc.response.status_code,
                    },
                },
            )
            raise RagIngestionError(
                f"RAG ingestion request failed with {exc.response.status_code}: {exc.response.text}"
            ) from exc

        logger.info(
            "RAG ingestion request completed",
            extra={
                "event": "rag_request_completed",
                "integration": "rag_ingestion",
                "http": {"method": method, "path": path, "status_code": response.status_code},
            },
        )
        return response.json()

    def _project_value(self, artifact: KnowledgeCaptureArtifact) -> str | None:
        project = artifact.manifest.project
        if project is None:
            return None

        return project.project_slug or project.project_id or project.project_path
