from datetime import UTC, datetime, timedelta

from app.platform.execution_targets.health import target_is_online
from app.platform.execution_targets.models import ExecutionTarget


def build_target(*, enabled: bool = True, seconds_ago: float | None = None) -> ExecutionTarget:
    last_seen_at = None
    if seconds_ago is not None:
        last_seen_at = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    return ExecutionTarget(
        id="mbp-primary",
        display_name="MacBook Pro",
        executor_type="worker_agent",
        enabled=enabled,
        is_default=False,
        labels_json=[],
        supported_tools_json=["agent.execute_coding_task"],
        metadata_json={},
        last_seen_at=last_seen_at,
    )


def test_target_is_online_when_recently_seen():
    assert target_is_online(build_target(seconds_ago=5)) is True


def test_target_is_offline_when_not_seen_recently():
    assert target_is_online(build_target(seconds_ago=120)) is False


def test_target_is_offline_when_disabled():
    assert target_is_online(build_target(enabled=False, seconds_ago=5)) is False
