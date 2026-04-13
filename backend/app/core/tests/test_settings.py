from app.core.settings import Settings


def test_settings_accept_agent_scoped_aliases(monkeypatch):
    keys_to_clear = [
        "ENV",
        "LOG_LEVEL",
        "API_PREFIX",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "PG_ADMIN_USER",
        "PG_ADMIN_PASSWORD",
        "APP_DB_USER",
        "APP_DB_PASSWORD",
        "DEFAULT_EXECUTION_TARGET",
        "WORKER_SECRET_REFS",
        "REMOTE_EXECUTION_POLL_INTERVAL_SECONDS",
        "REMOTE_EXECUTION_WAIT_TIMEOUT_SECONDS",
        "REMOTE_EXECUTION_ONLINE_THRESHOLD_SECONDS",
        "CONTROL_HUB_BASE_URL",
        "RAG_INGESTION_ENABLED",
        "RAG_INGESTION_BASE_URL",
        "RAG_INGESTION_TIMEOUT_SECONDS",
    ]
    for key in keys_to_clear:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("AGENT_ENV", "production")
    monkeypatch.setenv("AGENT_LOG_LEVEL", "INFO")
    monkeypatch.setenv("AGENT_API_PREFIX", "/api")
    monkeypatch.setenv("AGENT_POSTGRES_HOST", "postgres_db")
    monkeypatch.setenv("AGENT_POSTGRES_PORT", "5432")
    monkeypatch.setenv("AGENT_POSTGRES_DB", "agent_service")
    monkeypatch.setenv("AGENT_PG_ADMIN_USER", "spencerwood")
    monkeypatch.setenv("AGENT_PG_ADMIN_PASSWORD", "secret-admin")
    monkeypatch.setenv("AGENT_APP_DB_USER", "agent_service_app")
    monkeypatch.setenv("AGENT_APP_DB_PASSWORD", "secret-app")
    monkeypatch.setenv("AGENT_DEFAULT_EXECUTION_TARGET", "mbp-primary")
    monkeypatch.setenv(
        "AGENT_WORKER_SECRET_REFS",
        '{"mbp-primary-token":"abc","worker-b-token":"def"}',
    )
    monkeypatch.setenv("AGENT_REMOTE_EXECUTION_POLL_INTERVAL_SECONDS", "2")
    monkeypatch.setenv("AGENT_REMOTE_EXECUTION_WAIT_TIMEOUT_SECONDS", "900")
    monkeypatch.setenv("AGENT_REMOTE_EXECUTION_ONLINE_THRESHOLD_SECONDS", "30")
    monkeypatch.setenv("AGENT_CONTROL_HUB_BASE_URL", "https://control.example.com/api")
    monkeypatch.setenv("AGENT_RAG_INGESTION_ENABLED", "false")
    monkeypatch.setenv("AGENT_RAG_INGESTION_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("AGENT_RAG_INGESTION_TIMEOUT_SECONDS", "15")

    settings = Settings()

    assert settings.environment == "production"
    assert settings.log_level == "INFO"
    assert settings.api_prefix == "/api"
    assert settings.postgres_host == "postgres_db"
    assert settings.postgres_port == 5432
    assert settings.postgres_db == "agent_service"
    assert settings.pg_admin_user == "spencerwood"
    assert settings.pg_admin_password == "secret-admin"
    assert settings.app_db_user == "agent_service_app"
    assert settings.app_db_password == "secret-app"
    assert settings.default_execution_target == "mbp-primary"
    assert settings.worker_secret_refs == {
        "mbp-primary-token": "abc",
        "worker-b-token": "def",
    }
    assert settings.control_hub_base_url == "https://control.example.com/api"
    assert settings.remote_execution_online_threshold_seconds == 30.0
    assert settings.database_url.endswith("@postgres_db:5432/agent_service")
