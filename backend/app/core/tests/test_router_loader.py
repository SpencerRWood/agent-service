from app.main import create_app


def test_create_app_registers_tool_and_webhook_routers():
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/api/orchestration/tools/control-hub-chat/run" in paths
    assert "/api/orchestration/webhooks/github" in paths
