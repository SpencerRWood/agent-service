from app.features.orchestration.models import ExecutionStatus


def test_create_run_endpoint(client):
    response = client.post(
        "/api/orchestration/runs/",
        json={"user_prompt": "Add orchestration status endpoint", "repo": "agent-service"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["execution_status"] == ExecutionStatus.AWAITING_APPROVAL.value
    assert payload["control_hub_approval_id"] == 1


def test_list_runs_endpoint(client):
    client.post(
        "/api/orchestration/runs/", json={"user_prompt": "Add endpoint", "repo": "agent-service"}
    )

    response = client.get("/api/orchestration/runs/")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1


def test_reconcile_endpoint_dispatches_execution(client, orchestration_dependencies):
    run_response = client.post(
        "/api/orchestration/runs/",
        json={"user_prompt": "Implement provider routing", "repo": "agent-service"},
    )
    run_id = run_response.json()["id"]
    approval_id = run_response.json()["control_hub_approval_id"]
    orchestration_dependencies["control_hub"].set_status(approval_id, "APPROVED")

    response = client.post(f"/api/orchestration/runs/{run_id}/reconcile")

    assert response.status_code == 200
    payload = response.json()["run"]
    assert payload["execution_status"] == ExecutionStatus.PR_OPEN.value
    assert payload["pr_number"] == 101


def test_control_hub_chat_tool_endpoint(client):
    response = client.post(
        "/api/orchestration/tools/control-hub-chat/run",
        json={
            "prompt": "Add audit logging to the orchestration flow",
            "context": {
                "conversation_id": "conv-1",
                "message_id": "msg-1",
                "repo": "agent-service",
                "requested_by": "control-hub-chat",
            },
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["approval_item_id"] == 1
    assert payload["execution_status"] == ExecutionStatus.AWAITING_APPROVAL.value


def test_control_hub_chat_tool_status_endpoint(client):
    create_response = client.post(
        "/api/orchestration/tools/control-hub-chat/run",
        json={"prompt": "Add audit logging", "context": {"repo": "agent-service"}},
    )
    run_id = create_response.json()["run_id"]

    response = client.get(f"/api/orchestration/tools/control-hub-chat/run/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == run_id
    assert "Waiting for Control Hub approval" in payload["summary"]


def test_control_hub_chat_tool_carries_project_context_and_target(
    client, orchestration_dependencies
):
    response = client.post(
        "/api/orchestration/tools/control-hub-chat/run",
        json={
            "prompt": "Scope execution to a project",
            "context": {
                "repo": "agent-service",
                "project": {
                    "project_id": "proj_456",
                    "project_slug": "control-hub",
                    "project_path": "apps/control-hub",
                },
                "worker_target": "worker_b",
            },
        },
    )

    assert response.status_code == 201
    run_id = response.json()["run_id"]
    stored_run = orchestration_dependencies["repository"].items[run_id]
    assert stored_run.source_metadata_json["project"]["project_slug"] == "control-hub"
    assert stored_run.source_metadata_json["worker_target"] == "worker_b"


def test_github_webhook_updates_run_by_pull_request_number(client, orchestration_dependencies):
    run_response = client.post(
        "/api/orchestration/runs/",
        json={"user_prompt": "Implement provider routing", "repo": "agent-service"},
    )
    run_id = run_response.json()["id"]
    approval_id = run_response.json()["control_hub_approval_id"]
    orchestration_dependencies["control_hub"].set_status(approval_id, "APPROVED")
    client.post(f"/api/orchestration/runs/{run_id}/reconcile")

    response = client.post(
        "/api/orchestration/webhooks/github",
        headers={"X-GitHub-Event": "pull_request_review"},
        json={
            "action": "submitted",
            "repository": {"name": "agent-service"},
            "pull_request": {"number": 101},
            "review": {"state": "approved", "user": {"login": "reviewer-b"}},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] is True
    assert orchestration_dependencies["repository"].items[run_id].pr_status == "approved"
