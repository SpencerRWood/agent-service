from app.platform.execution_targets.models import ExecutionTarget
from app.platform.execution_targets.routing import select_execution_target


def build_target(
    target_id: str,
    *,
    is_default: bool = False,
    target_kind: str = "generic",
    labels: list[str] | None = None,
    supported_tools: list[str] | None = None,
) -> ExecutionTarget:
    return ExecutionTarget(
        id=target_id,
        display_name=target_id,
        executor_type="worker_agent",
        enabled=True,
        is_default=is_default,
        labels_json=labels or [],
        supported_tools_json=supported_tools or ["agent.run_task"],
        metadata_json={"target_kind": target_kind},
    )


def test_select_execution_target_uses_explicit_target():
    targets = [
        build_target("mbp-primary", target_kind="macbook"),
        build_target("server-default", is_default=True),
    ]

    selected = select_execution_target(
        candidates=targets,
        explicit_target_id="mbp-primary",
        configured_default_target_id=None,
        routing_context=None,
    )

    assert selected is not None
    assert selected.id == "mbp-primary"


def test_select_execution_target_prefers_macbook_for_coding_prompt():
    targets = [
        build_target("server-default", is_default=True, target_kind="generic"),
        build_target("mbp-primary", target_kind="macbook", labels=["mac"]),
    ]

    selected = select_execution_target(
        candidates=targets,
        explicit_target_id=None,
        configured_default_target_id=None,
        routing_context={"prompt": "Refactor repo branch workflow for codex"},
    )

    assert selected is not None
    assert selected.id == "mbp-primary"


def test_select_execution_target_prefers_gpu_route_profile():
    targets = [
        build_target("mbp-primary", target_kind="macbook"),
        build_target("gpu-future", target_kind="gpu"),
    ]
    targets[1].metadata_json["route_profile"] = "gpu"

    selected = select_execution_target(
        candidates=targets,
        explicit_target_id=None,
        configured_default_target_id=None,
        routing_context={"prompt": "Run this with a local model", "route_profile": "gpu"},
    )

    assert selected is not None
    assert selected.id == "gpu-future"


def test_select_execution_target_allows_wildcard_supported_tools():
    targets = [
        build_target(
            "mbp-primary",
            is_default=True,
            target_kind="macbook",
            supported_tools=["*"],
        ),
    ]

    selected = select_execution_target(
        candidates=targets,
        explicit_target_id=None,
        configured_default_target_id="mbp-primary",
        routing_context={"prompt": "Promote a staged knowledge artifact"},
    )

    assert selected is not None
    assert selected.id == "mbp-primary"
