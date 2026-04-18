from pydantic import BaseModel


class HealthRuntimeConfigResponse(BaseModel):
    opencode_dry_run: bool
    opencode_dry_run_raw: str | None = None
    opencode_command: str
    orchestration_dry_run: bool


class HealthResponse(BaseModel):
    status: str
    runtime: HealthRuntimeConfigResponse
