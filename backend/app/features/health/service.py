import os

from app.core.settings import settings


class HealthService:
    def get(self):
        return {
            "status": "ok",
            "runtime": {
                "opencode_dry_run": settings.opencode_dry_run,
                "opencode_dry_run_raw": os.getenv("OPENCODE_DRY_RUN"),
                "opencode_command": settings.opencode_command,
                "orchestration_dry_run": settings.orchestration_dry_run,
            },
        }
