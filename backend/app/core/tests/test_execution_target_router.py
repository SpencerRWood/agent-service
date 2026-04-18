from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.settings import settings
from app.platform.agent_tasks.router import get_agent_task_service
from app.platform.execution_targets.router import (
    get_execution_target_service,
    job_router,
    router,
    worker_router,
)
from app.platform.execution_targets.schemas import (
    ExecutionJobListResponse,
    ExecutionJobRead,
    ExecutionTargetHealthRead,
    ExecutionTargetRead,
)


class FakeExecutionTargetService:
    def __init__(self) -> None:
        self.completed_calls = []

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

    async def _require_target(self, target_id):
        assert target_id == "worker-b"
        return type("Target", (), {"secret_ref": "worker-token"})()

    async def complete_job(self, *, target_id, job_id, request):
        self.completed_calls.append((target_id, job_id, request))
        return ExecutionJobRead(
            id=job_id,
            target_id=target_id,
            tool_name="agent.run_task",
            status="completed",
            payload_json={"task": {"task_id": job_id}},
            result_json={
                "state": "completed",
                "backend": "codex",
                "execution_mode": "opencode",
                "summary": "Review completed with fixes suggested.",
                "workflow_outcome": "needs_changes",
                "reason_code": None,
                "raw_output": {},
                "artifacts": [],
                "metrics": {},
                "completed_at": "2026-04-10T00:00:02Z",
            },
            error_json=None,
            claimed_by="worker-b",
            created_at="2026-04-10T00:00:00Z",
            claimed_at="2026-04-10T00:00:01Z",
            completed_at="2026-04-10T00:00:02Z",
        )


class FakeAgentTaskService:
    def __init__(self) -> None:
        self.completed_jobs = []

    async def handle_completed_job(self, *, task_id, result_payload):
        self.completed_jobs.append((task_id, result_payload))
        return None


def build_client() -> TestClient:
    app = FastAPI()
    service = FakeExecutionTargetService()
    agent_task_service = FakeAgentTaskService()
    app.include_router(router, prefix=settings.api_prefix)
    app.include_router(job_router, prefix=settings.api_prefix)
    app.include_router(worker_router, prefix=settings.api_prefix)
    app.dependency_overrides[get_execution_target_service] = lambda: service
    app.dependency_overrides[get_agent_task_service] = lambda: agent_task_service
    app.state.fake_execution_target_service = service
    app.state.fake_agent_task_service = agent_task_service
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


def test_complete_execution_job_triggers_agent_task_handoff_hook():
    previous_secret = settings.worker_secret_refs.get("worker-token")
    settings.worker_secret_refs["worker-token"] = "secret"
    client = build_client()
    try:
        response = client.post(
            "/api/worker/execution-targets/worker-b/jobs/task-1/complete",
            headers={"X-Worker-Token": "secret"},
            json={
                "worker_id": "worker-b",
                "result": {
                    "state": "completed",
                    "backend": "codex",
                    "execution_mode": "opencode",
                    "summary": "Review completed with fixes suggested.",
                    "workflow_outcome": "needs_changes",
                    "reason_code": None,
                    "raw_output": {},
                    "artifacts": [],
                    "metrics": {},
                    "completed_at": "2026-04-10T00:00:02Z",
                },
            },
        )

        assert response.status_code == 200
        assert client.app.state.fake_execution_target_service.completed_calls
        assert client.app.state.fake_agent_task_service.completed_jobs == [
            (
                "task-1",
                {
                    "state": "completed",
                    "backend": "codex",
                    "execution_mode": "opencode",
                    "summary": "Review completed with fixes suggested.",
                    "workflow_outcome": "needs_changes",
                    "reason_code": None,
                    "raw_output": {},
                    "artifacts": [],
                    "metrics": {},
                    "completed_at": "2026-04-10T00:00:02Z",
                },
            )
        ]
    finally:
        if previous_secret is None:
            settings.worker_secret_refs.pop("worker-token", None)
        else:
            settings.worker_secret_refs["worker-token"] = previous_secret
