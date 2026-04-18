def test_health_endpoint(client):
    response = client.get("/api/health/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["runtime"]["opencode_dry_run"] in {True, False}
    assert "opencode_dry_run_raw" in payload["runtime"]
    assert "opencode_command" in payload["runtime"]
    assert "orchestration_dry_run" in payload["runtime"]
