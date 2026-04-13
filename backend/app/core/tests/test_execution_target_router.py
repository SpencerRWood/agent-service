from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.settings import settings
from app.platform.execution_targets.router import get_execution_target_service, job_router, router
from app.platform.execution_targets.schemas import (
    ExecutionJobListResponse,
    ExecutionTargetHealthRead,
    ExecutionTargetRead,
)


class FakeExecutionTargetService:
    async def create_target(self, request):
        return ExecutionTargetRead(
            id=request.id,
            display_name=request.display_name,
            executor_type=request.executor_type,
            host=request.host,
            port=request.port,
            user_name=request.user_name,
            repo_root=request.repo_root,
            labels_json=request.labels,
            supported_tools_json=request.supported_tools,
            metadata_json=request.metadata,
            secret_ref=request.secret_ref,
            enabled=request.enabled,
            is_default=request.is_default,
            archived_at=None,
            last_seen_at=None,
            created_at="2026-04-10T00:00:00Z",
            updated_at="2026-04-10T00:00:00Z",
        )

    async def list_targets(self):
        return [
            ExecutionTargetRead(
                id="worker-b",
                display_name="Worker B",
                executor_type="worker_agent",
                host="worker.internal",
                port=22,
                user_name="agent",
                repo_root="/srv/agent-service",
                labels_json=["mac", "worker"],
                supported_tools_json=["agent.run_task"],
                metadata_json={"route_profile": "implementation"},
                secret_ref="worker-token",
                enabled=True,
                is_default=True,
                archived_at=None,
                last_seen_at=None,
                created_at="2026-04-10T00:00:00Z",
                updated_at="2026-04-10T00:00:00Z",
            )
        ]

    async def get_target_health(self, target_id):
        return ExecutionTargetHealthRead(
            target_id=target_id,
            display_name="Worker B",
            enabled=True,
            online=False,
            executor_type="worker_agent",
            last_seen_at=None,
            labels=["mac", "worker"],
            supported_tools=["agent.run_task"],
        )

    async def list_jobs(self, target_id=None, limit=50):
        del target_id, limit
        return ExecutionJobListResponse(items=[])

    async def delete_target(self, target_id):
        assert target_id == "worker-b"
        return None


def build_client() -> TestClient:
    app = FastAPI()
    service = FakeExecutionTargetService()
    app.include_router(router, prefix=settings.api_prefix)
    app.include_router(job_router, prefix=settings.api_prefix)
    app.dependency_overrides[get_execution_target_service] = lambda: service
    return TestClient(app)


def test_list_execution_targets_returns_created_worker_nodes():
    client = build_client()

    response = client.get("/api/admin/execution-targets/")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == "worker-b"
    assert payload[0]["supported_tools_json"] == ["agent.run_task"]


def test_create_execution_target_returns_created_record():
    client = build_client()

    response = client.post(
        "/api/admin/execution-targets/",
        json={
            "id": "worker-c",
            "display_name": "Worker C",
            "executor_type": "worker_agent",
            "host": "worker-c.internal",
            "port": 22,
            "user_name": "agent",
            "repo_root": "/srv/agent-service",
            "labels": ["gpu", "worker"],
            "supported_tools": ["agent.run_task"],
            "metadata": {"route_profile": "gpu"},
            "secret_ref": "worker-c-token",
            "enabled": True,
            "is_default": False,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"] == "worker-c"
    assert payload["supported_tools_json"] == ["agent.run_task"]


def test_execution_target_health_route_returns_worker_status():
    client = build_client()

    response = client.get("/api/admin/execution-targets/worker-b/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_id"] == "worker-b"
    assert payload["supported_tools"] == ["agent.run_task"]


def test_delete_execution_target_returns_no_content():
    client = build_client()

    response = client.delete("/api/admin/execution-targets/worker-b")

    assert response.status_code == 204
    assert response.text == ""
