from __future__ import annotations

from datetime import UTC, datetime

from app.core.settings import settings
from app.platform.execution_targets.models import ExecutionTarget


def target_is_online(target: ExecutionTarget) -> bool:
    if not target.enabled or target.last_seen_at is None:
        return False
    now = datetime.now(UTC)
    last_seen = target.last_seen_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    age = (now - last_seen).total_seconds()
    return age <= settings.remote_execution_online_threshold_seconds
