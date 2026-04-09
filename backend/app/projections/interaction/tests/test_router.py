import pytest
from fastapi.testclient import TestClient

from app.features.orchestration.dependencies import get_orchestration_service
from app.features.orchestration.service import OrchestrationService
from app.features.orchestration.tests.conftest import (
    FakeControlHubClient,
    FakePlatformRecorder,
    FakeProviderRouter,
    FakePullRequestStateClient,
    FakeRagClient,
    FakeRepository,
)
from app.main import create_app
from app.projections.interaction.app import create_interaction_app
from app.projections.interaction.router import get_control_hub_client


@pytest.fixture
def orchestration_dependencies():
    repository = FakeRepository()
    control_hub = FakeControlHubClient()
    pr_client = FakePullRequestStateClient()
    rag_client = FakeRagClient()
    platform_recorder = FakePlatformRecorder()
    service = OrchestrationService(
        repository=repository,
        control_hub_client=control_hub,
        provider_router=FakeProviderRouter(),
        rag_client=rag_client,
        pr_state_client=pr_client,
        platform_recorder=platform_recorder,
    )
    return {
        "repository": repository,
        "control_hub": control_hub,
        "pr_client": pr_client,
        "rag_client": rag_client,
        "platform_recorder": platform_recorder,
        "service": service,
    }


def build_client(orchestration_dependencies):
    app = create_interaction_app()
    control_hub = orchestration_dependencies["control_hub"]
    app.dependency_overrides[get_orchestration_service] = lambda: orchestration_dependencies[
        "service"
    ]
    app.dependency_overrides[get_control_hub_client] = lambda: control_hub
    return TestClient(app)


def test_create_request_projection(orchestration_dependencies):
    client = build_client(orchestration_dependencies)

    response = client.post(
        "/requests",
        json={
            "prompt": "Add audit logging to orchestration",
            "repo": "agent-service",
            "conversation_id": "conv-1",
            "username": "spencer",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["approval_item_id"] == 1
    assert payload["execution_status"] == "awaiting_approval"


def test_create_request_projection_carries_execution_target_hint(orchestration_dependencies):
    client = build_client(orchestration_dependencies)

    response = client.post(
        "/requests",
        json={
            "prompt": "Run this on my MacBook",
            "repo": "agent-service",
            "extra": {"execution_target": "mbp-primary"},
        },
    )

    assert response.status_code == 201
    run_id = response.json()["run_id"]
    stored_run = orchestration_dependencies["repository"].items[run_id]
    assert stored_run.source_metadata_json["execution_target"] == "mbp-primary"


def test_approve_request_projection(orchestration_dependencies):
    client = build_client(orchestration_dependencies)

    created = client.post(
        "/requests",
        json={"prompt": "Implement provider routing", "repo": "agent-service"},
    ).json()

    response = client.post(
        f"/requests/{created['run_id']}/approve",
        json={"decided_by": "reviewer-a", "decision_reason": "Looks good"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_status"] == "pr_open"
    assert payload["pr_status"] == "open"


def test_reject_request_projection(orchestration_dependencies):
    client = build_client(orchestration_dependencies)

    created = client.post(
        "/requests",
        json={"prompt": "Delete old feature flags", "repo": "agent-service"},
    ).json()

    response = client.post(
        f"/requests/{created['run_id']}/reject",
        json={"decided_by": "reviewer-a", "decision_reason": "Too risky"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_status"] == "rejected"
    assert "rejected" in payload["summary"].lower()


def test_pull_request_event_projection(orchestration_dependencies):
    client = build_client(orchestration_dependencies)

    created = client.post(
        "/requests",
        json={"prompt": "Implement provider routing", "repo": "agent-service"},
    ).json()
    client.post(
        f"/requests/{created['run_id']}/approve",
        json={"decided_by": "reviewer-a", "decision_reason": "Looks good"},
    )

    response = client.post(
        f"/requests/{created['run_id']}/pull-request-events",
        json={"status": "approved", "approved_by": ["reviewer-a"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_status"] == "docs_staged"
    assert payload["rag_status"] == "provisional"


def test_main_app_mount_exposes_interaction_openapi():
    client = TestClient(create_app())

    response = client.get("/api/interaction/openapi.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["info"]["title"] == "Agent Service Interaction API"
