from __future__ import annotations

from collections.abc import Sequence

from app.platform.execution_targets.models import ExecutionTarget

GPU_KEYWORDS = {"gpu", "cuda", "vram", "mlx", "ollama", "local model", "llama"}
MAC_KEYWORDS = {"codex", "copilot", "repo", "pull request", "branch", "commit", "refactor"}


def select_execution_target(
    *,
    candidates: Sequence[ExecutionTarget],
    explicit_target_id: str | None,
    configured_default_target_id: str | None,
    routing_context: dict | None,
) -> ExecutionTarget | None:
    if not candidates:
        return None

    if explicit_target_id:
        for candidate in candidates:
            if candidate.id == explicit_target_id:
                return candidate
        return None

    prompt = ""
    route_profile = None
    if routing_context:
        prompt = str(routing_context.get("prompt") or "").lower()
        route_profile = routing_context.get("route_profile")

    if route_profile:
        matched = _match_by_route_profile(candidates, str(route_profile))
        if matched is not None:
            return matched

    if any(keyword in prompt for keyword in GPU_KEYWORDS):
        matched = _match_by_target_kind(candidates, {"gpu"})
        if matched is not None:
            return matched

    if any(keyword in prompt for keyword in MAC_KEYWORDS):
        matched = _match_by_target_kind(candidates, {"developer_workstation", "macbook", "mac"})
        if matched is not None:
            return matched

    if configured_default_target_id:
        for candidate in candidates:
            if candidate.id == configured_default_target_id:
                return candidate

    for candidate in candidates:
        if candidate.is_default:
            return candidate

    return candidates[0]


def _match_by_route_profile(
    candidates: Sequence[ExecutionTarget],
    route_profile: str,
) -> ExecutionTarget | None:
    for candidate in candidates:
        profile = (candidate.metadata_json or {}).get("route_profile")
        if profile == route_profile:
            return candidate
    return None


def _match_by_target_kind(
    candidates: Sequence[ExecutionTarget],
    expected_kinds: set[str],
) -> ExecutionTarget | None:
    for candidate in candidates:
        metadata = candidate.metadata_json or {}
        target_kind = str(metadata.get("target_kind") or "").lower()
        labels = {str(label).lower() for label in (candidate.labels_json or [])}
        if target_kind in expected_kinds or labels.intersection(expected_kinds):
            return candidate
    return None
