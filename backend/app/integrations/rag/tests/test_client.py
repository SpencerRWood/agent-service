import asyncio

import httpx

from app.features.orchestration.models import ProviderName
from app.features.orchestration.schemas import (
    ArtifactFile,
    ArtifactManifest,
    ArtifactStage,
    KnowledgeCaptureArtifact,
    WorkerTarget,
)
from app.integrations.rag.client import HttpRagIngestionClient, NoOpRagIngestionClient


def build_artifact() -> KnowledgeCaptureArtifact:
    return KnowledgeCaptureArtifact(
        manifest=ArtifactManifest(
            artifact_id="artifact-123",
            repo="agent-service",
            provider=ProviderName.CODEX,
            worker_target=WorkerTarget.WORKER_B,
            stage=ArtifactStage.PROVISIONAL,
            generated_at="2026-04-01T00:00:00Z",
            source_run_id="run-123",
            source_pr_url="https://git/pull/1",
            source_pr_number=1,
            tags=["agent-service"],
        ),
        implementation_summary="summary",
        operational_notes=["note"],
        decision_log=["decision"],
        knowledge_chunks=["chunk"],
        documents=[
            ArtifactFile.from_content(
                path="artifacts/run-123/implementation-summary.md",
                media_type="text/markdown",
                title="Implementation Summary",
                content="hello",
            )
        ],
        source_pr_url="https://git/pull/1",
        provisional=True,
    )


def test_noop_rag_client_returns_receipt():
    client = NoOpRagIngestionClient()

    receipt = asyncio.run(client.stage_provisional(build_artifact()))

    assert receipt.status == "noop"
    assert receipt.operation == "stage_provisional"
    assert receipt.artifact_id == "artifact-123"


def test_http_rag_client_stages_artifact():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ingest/text"
        return httpx.Response(
            201,
            json={
                "document_id": "11111111-1111-1111-1111-111111111111",
                "chunk_count": 2,
                "status": "indexed",
                "file_name": None,
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="https://rag.example")
    client = HttpRagIngestionClient(base_url="https://rag.example", client=http_client)

    receipt = asyncio.run(client.stage_provisional(build_artifact()))

    assert receipt.status == "indexed"
    assert receipt.remote_id == "11111111-1111-1111-1111-111111111111"
    assert receipt.metadata["document_count"] == 1
    assert receipt.metadata["documents"][0]["chunk_count"] == 2


def test_http_rag_client_promote_is_local_only():
    client = HttpRagIngestionClient(base_url="https://rag.example")

    receipt = asyncio.run(client.promote(build_artifact()))

    assert receipt.status == "local_only"
    assert receipt.operation == "promote"


def test_http_rag_client_mark_stale_is_local_only():
    client = HttpRagIngestionClient(base_url="https://rag.example")

    receipt = asyncio.run(client.mark_stale(build_artifact(), reason="closed before merge"))

    assert receipt.status == "local_only"
    assert receipt.operation == "mark_stale"
    assert receipt.metadata["reason"] == "closed before merge"
