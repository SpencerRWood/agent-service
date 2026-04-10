import json
from pathlib import Path

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        extra="ignore",
    )

    app_name: str = Field(default="Service Template", validation_alias="APP_NAME")
    app_version: str = Field(default="0.1.0", validation_alias="APP_VERSION")
    environment: str = Field(default="development", validation_alias="ENV")
    debug: bool = Field(default=False, validation_alias="DEBUG")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    api_prefix: str = Field(default="/api", validation_alias="API_PREFIX")
    cors_origins: list[str] = Field(
        default=["http://localhost:5173"],
        validation_alias="CORS_ORIGINS",
    )
    app_host: str = Field(default="127.0.0.1", validation_alias="APP_HOST")
    app_port: int = Field(default=8000, validation_alias="APP_PORT")
    control_hub_base_url: str = Field(
        default="https://control.woodhost.cloud/api",
        validation_alias="CONTROL_HUB_BASE_URL",
    )
    control_hub_timeout_seconds: float = Field(
        default=15.0,
        validation_alias="CONTROL_HUB_TIMEOUT_SECONDS",
    )
    rag_ingestion_base_url: str = Field(
        default="http://localhost:8080",
        validation_alias="RAG_INGESTION_BASE_URL",
    )
    rag_ingestion_timeout_seconds: float = Field(
        default=15.0,
        validation_alias="RAG_INGESTION_TIMEOUT_SECONDS",
    )
    rag_ingestion_enabled: bool = Field(
        default=False,
        validation_alias="RAG_INGESTION_ENABLED",
    )
    orchestration_default_provider: str = Field(
        default="codex",
        validation_alias="ORCHESTRATION_DEFAULT_PROVIDER",
    )
    orchestration_provider_repo_overrides: dict[str, str] = Field(
        default_factory=dict,
        validation_alias="ORCHESTRATION_PROVIDER_REPO_OVERRIDES",
    )
    orchestration_provider_fallback_enabled: bool = Field(
        default=False,
        validation_alias="ORCHESTRATION_PROVIDER_FALLBACK_ENABLED",
    )
    orchestration_default_requested_by: str = Field(
        default="agent-a",
        validation_alias="ORCHESTRATION_DEFAULT_REQUESTED_BY",
    )
    orchestration_default_assigned_to: str | None = Field(
        default=None,
        validation_alias="ORCHESTRATION_DEFAULT_ASSIGNED_TO",
    )
    orchestration_default_worker_target: str = Field(
        default="worker_b",
        validation_alias="ORCHESTRATION_DEFAULT_WORKER_TARGET",
    )
    orchestration_default_repo: str = Field(
        default="default",
        validation_alias="ORCHESTRATION_DEFAULT_REPO",
    )
    orchestration_dry_run: bool = Field(
        default=True,
        validation_alias="ORCHESTRATION_DRY_RUN",
    )
    codex_command: str = Field(default="codex", validation_alias="CODEX_COMMAND")
    copilot_cli_command: str = Field(
        default="copilot",
        validation_alias="COPILOT_CLI_COMMAND",
    )
    opencode_command: str = Field(default="opencode", validation_alias="OPENCODE_COMMAND")
    opencode_dry_run: bool = Field(default=True, validation_alias="OPENCODE_DRY_RUN")
    local_llm_command: str = Field(
        default="local-llm",
        validation_alias="LOCAL_LLM_COMMAND",
    )
    local_llm_dry_run: bool = Field(
        default=True,
        validation_alias="LOCAL_LLM_DRY_RUN",
    )
    git_provider_name: str = Field(
        default="github",
        validation_alias="GIT_PROVIDER_NAME",
    )
    github_api_base_url: str = Field(
        default="https://api.github.com",
        validation_alias="GITHUB_API_BASE_URL",
    )
    github_owner: str | None = Field(
        default=None,
        validation_alias="GITHUB_OWNER",
    )
    github_token: str | None = Field(
        default=None,
        validation_alias="GITHUB_TOKEN",
    )
    github_webhook_secret: str | None = Field(
        default=None,
        validation_alias="GITHUB_WEBHOOK_SECRET",
    )
    default_execution_target: str | None = Field(
        default=None,
        validation_alias="DEFAULT_EXECUTION_TARGET",
    )
    worker_secret_refs: dict[str, str] = Field(
        default_factory=dict,
        validation_alias="WORKER_SECRET_REFS",
    )
    remote_execution_poll_interval_seconds: float = Field(
        default=2.0,
        validation_alias="REMOTE_EXECUTION_POLL_INTERVAL_SECONDS",
    )
    remote_execution_wait_timeout_seconds: float = Field(
        default=900.0,
        validation_alias="REMOTE_EXECUTION_WAIT_TIMEOUT_SECONDS",
    )
    remote_execution_online_threshold_seconds: float = Field(
        default=30.0,
        validation_alias="REMOTE_EXECUTION_ONLINE_THRESHOLD_SECONDS",
    )

    postgres_host: str
    postgres_port: int
    postgres_db: str

    pg_admin_user: str
    pg_admin_password: str

    app_db_user: str
    app_db_password: str

    @computed_field
    @property
    def database_url(self) -> str:
        """Async DSN used by the application."""
        return (
            f"postgresql+asyncpg://"
            f"{self.app_db_user}:{self.app_db_password}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_db}"
        )

    @computed_field
    @property
    def sync_database_url(self) -> str:
        """Sync DSN used by Alembic and admin scripts."""
        return (
            f"postgresql+psycopg://"
            f"{self.app_db_user}:{self.app_db_password}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_db}"
        )

    @computed_field
    @property
    def admin_dsn(self) -> str:
        """Sync DSN used only for provisioning against the default postgres DB."""
        return (
            f"postgresql://"
            f"{self.pg_admin_user}:{self.pg_admin_password}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/postgres"
        )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value

        if not value:
            return []

        return [origin.strip() for origin in value.split(",") if origin.strip()]

    @field_validator(
        "debug",
        "rag_ingestion_enabled",
        "opencode_dry_run",
        "local_llm_dry_run",
        mode="before",
    )
    @classmethod
    def parse_boolish(cls, value: bool | str) -> bool:
        if isinstance(value, bool):
            return value

        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "debug"}:
            return True
        if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
            return False

        raise ValueError("Expected a boolean-like string value")

    @field_validator("orchestration_provider_repo_overrides", mode="before")
    @classmethod
    def parse_provider_overrides(cls, value: str | dict[str, str] | None) -> dict[str, str]:
        if value in (None, ""):
            return {}

        if isinstance(value, dict):
            return value

        loaded = json.loads(value)
        if not isinstance(loaded, dict):
            raise ValueError("ORCHESTRATION_PROVIDER_REPO_OVERRIDES must be a JSON object")

        return {str(repo): str(provider) for repo, provider in loaded.items()}

    @field_validator("worker_secret_refs", mode="before")
    @classmethod
    def parse_worker_secret_refs(
        cls,
        value: str | dict[str, str] | None,
    ) -> dict[str, str]:
        if value in (None, ""):
            return {}

        if isinstance(value, dict):
            return {str(secret_id): str(secret_value) for secret_id, secret_value in value.items()}

        loaded = json.loads(value)
        if not isinstance(loaded, dict):
            raise ValueError("WORKER_SECRET_REFS must be a JSON object")

        return {str(secret_id): str(secret_value) for secret_id, secret_value in loaded.items()}


settings = Settings()  # type: ignore[call-arg]
