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
    api_prefix: str = Field(default="", validation_alias="API_PREFIX")
    cors_origins: list[str] = Field(
        default=["http://localhost:5173"],
        validation_alias="CORS_ORIGINS",
    )
    app_host: str = Field(default="127.0.0.1", validation_alias="APP_HOST")
    app_port: int = Field(default=8000, validation_alias="APP_PORT")

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


settings = Settings()  # type: ignore[call-arg]
