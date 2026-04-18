from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.core.logging import get_logger
from app.platform.agents.defaults import DEFAULT_AGENT_CATALOG
from app.platform.agents.schemas import AgentCatalogDefinition

logger = get_logger(__name__)

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[3] / "config" / "agents.yaml"
LEGACY_CATALOG_PATH = Path(__file__).resolve().parents[3] / "config" / "agents.json"
OVERRIDE_CATALOG_PATH = Path(__file__).resolve().parents[3] / "config" / "agents.override.yaml"


def load_agent_catalog(path: Path | None = None) -> AgentCatalogDefinition:
    if path is not None:
        return _load_catalog_from_path(path)

    try:
        merged_payload = load_effective_catalog_payload()
        catalog = AgentCatalogDefinition.model_validate(merged_payload)
        _validate_catalog_references(catalog)
        return catalog
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        logger.warning(
            "Agent catalog config invalid; using built-in defaults",
            extra={"catalog_path": str(_discover_catalog_path()), "error": str(exc)},
        )
        return DEFAULT_AGENT_CATALOG.model_copy(deep=True)


def load_default_agent_catalog() -> AgentCatalogDefinition:
    payload = load_default_catalog_payload()
    catalog = AgentCatalogDefinition.model_validate(payload)
    _validate_catalog_references(catalog)
    return catalog


def load_default_catalog_payload() -> dict:
    payload = _load_catalog_payload(_discover_catalog_path())
    if not isinstance(payload, dict):
        raise ValueError("Agent catalog default must be a mapping object.")
    return payload


def load_agent_catalog_override_payload(path: Path | None = None) -> dict | None:
    override_path = path or OVERRIDE_CATALOG_PATH
    if not override_path.exists():
        return None
    payload = _load_catalog_payload(override_path)
    if not isinstance(payload, dict):
        raise ValueError("Agent catalog override must be a mapping object.")
    return payload


def load_effective_catalog_payload() -> dict:
    default_payload = load_default_catalog_payload()
    override_payload = load_agent_catalog_override_payload() or {}
    merged_payload = merge_catalog_payloads(default_payload, override_payload)
    if not isinstance(merged_payload, dict):
        raise ValueError("Effective agent catalog must be a mapping object.")
    return merged_payload


def merge_catalog_payloads(base: object, override: object) -> object:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = deepcopy(base)
        for key, value in override.items():
            if key in merged:
                merged[key] = merge_catalog_payloads(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged
    return deepcopy(override)


def validate_catalog_payload(payload: dict) -> AgentCatalogDefinition:
    catalog = AgentCatalogDefinition.model_validate(payload)
    _validate_catalog_references(catalog)
    return catalog


def save_agent_catalog_override_payload(payload: dict, path: Path | None = None) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Agent catalog override must be a mapping object.")

    merged_payload = merge_catalog_payloads(load_default_catalog_payload(), payload)
    if not isinstance(merged_payload, dict):
        raise ValueError("Effective agent catalog must be a mapping object.")
    validate_catalog_payload(merged_payload)

    override_path = path or OVERRIDE_CATALOG_PATH
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text(render_catalog_yaml(payload), encoding="utf-8")


def delete_agent_catalog_override(path: Path | None = None) -> None:
    override_path = path or OVERRIDE_CATALOG_PATH
    if override_path.exists():
        override_path.unlink()


def render_catalog_yaml(payload: object) -> str:
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)


def _load_catalog_from_path(path: Path) -> AgentCatalogDefinition:
    if not path.exists():
        logger.info(
            "Agent catalog config not found; using built-in defaults",
            extra={"catalog_path": str(path)},
        )
        return DEFAULT_AGENT_CATALOG.model_copy(deep=True)

    try:
        payload = _load_catalog_payload(path)
        catalog = AgentCatalogDefinition.model_validate(payload)
        _validate_catalog_references(catalog)
        return catalog
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        logger.warning(
            "Agent catalog config invalid; using built-in defaults",
            extra={"catalog_path": str(path), "error": str(exc)},
        )
        return DEFAULT_AGENT_CATALOG.model_copy(deep=True)


def _discover_catalog_path() -> Path:
    for candidate in (DEFAULT_CATALOG_PATH, LEGACY_CATALOG_PATH):
        if candidate.exists():
            return candidate
    return DEFAULT_CATALOG_PATH


def _load_catalog_payload(path: Path) -> object:
    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8")
    if suffix in {".yaml", ".yml"}:
        loaded = yaml.safe_load(raw)
        return loaded or {}
    return json.loads(raw)


def _validate_catalog_references(catalog: AgentCatalogDefinition) -> None:
    runtime_keys = {runtime.key for runtime in catalog.runtimes}
    missing_runtime_refs = sorted(
        {agent.runtime for agent in catalog.agents if agent.runtime not in runtime_keys}
    )
    if missing_runtime_refs:
        raise ValueError(
            "Agent catalog references undefined runtimes: " + ", ".join(missing_runtime_refs)
        )

    _ensure_unique_ids(
        values=[agent.id for agent in catalog.agents],
        kind="agent IDs",
    )
    _ensure_unique_ids(
        values=[runtime.key for runtime in catalog.runtimes],
        kind="runtime keys",
    )


def _ensure_unique_ids(*, values: list[str], kind: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"Agent catalog contains duplicate {kind}: {', '.join(duplicates)}")
