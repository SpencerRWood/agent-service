from app.main import create_app


def test_create_app_registers_platform_and_feature_routers():
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/api/health/" in paths
    assert "/api/agent-tasks/" in paths
    assert "/api/v1/models" in paths
    assert "/api/admin/execution-targets/" in paths
