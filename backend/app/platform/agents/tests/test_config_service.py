from pathlib import Path
from textwrap import dedent

from app.platform.agents import catalog as catalog_module
from app.platform.agents.config_service import AgentCatalogConfigService
from app.platform.agents.schemas import AgentCatalogDefinition


class FakeConfigRecord:
    def __init__(
        self, *, override_yaml: str | None = None, override_json: dict | None = None
    ) -> None:
        self.override_yaml = override_yaml
        self.override_json = override_json


class FakeAgentCatalogConfigRepository:
    def __init__(self) -> None:
        self.record: FakeConfigRecord | None = None

    async def get_default(self):
        return self.record

    async def upsert_default(self, *, override_yaml: str, override_json: dict):
        self.record = FakeConfigRecord(override_yaml=override_yaml, override_json=override_json)
        return self.record

    async def clear_default(self) -> None:
        self.record = None


def test_config_service_persists_override_to_repository_and_file(tmp_path: Path, monkeypatch):
    default_path = tmp_path / "agents.yaml"
    override_path = tmp_path / "agents.override.yaml"
    default_path.write_text(
        dedent(
            """
            agents:
              - id: reviewer
                display_name: Reviewer
                description: Default reviewer description.
                runtime: review_runtime
            runtimes:
              - key: review_runtime
                task_class: review
                route_profile: implementation
                approval_mode: required
            """
        ).strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(catalog_module, "DEFAULT_CATALOG_PATH", default_path)
    monkeypatch.setattr(catalog_module, "LEGACY_CATALOG_PATH", tmp_path / "agents.json")
    monkeypatch.setattr(catalog_module, "OVERRIDE_CATALOG_PATH", override_path)

    repository = FakeAgentCatalogConfigRepository()
    service = AgentCatalogConfigService(repository)

    config = _run(
        service.update_override_yaml(
            dedent(
                """
                agents:
                  - id: reviewer
                    display_name: Reviewer
                    description: Saved in database.
                    runtime: review_runtime
                """
            ).strip()
        )
    )

    assert repository.record is not None
    assert repository.record.override_json["agents"][0]["description"] == "Saved in database."
    assert "Saved in database." in (repository.record.override_yaml or "")
    assert override_path.exists()
    assert "Saved in database." in config.effective_yaml


def test_config_service_reset_clears_repository_and_override_file(tmp_path: Path, monkeypatch):
    default_path = tmp_path / "agents.yaml"
    override_path = tmp_path / "agents.override.yaml"
    default_path.write_text(
        dedent(
            """
            agents:
              - id: reviewer
                display_name: Reviewer
                description: Default reviewer description.
                runtime: review_runtime
            runtimes:
              - key: review_runtime
                task_class: review
                route_profile: implementation
                approval_mode: required
            """
        ).strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(catalog_module, "DEFAULT_CATALOG_PATH", default_path)
    monkeypatch.setattr(catalog_module, "LEGACY_CATALOG_PATH", tmp_path / "agents.json")
    monkeypatch.setattr(catalog_module, "OVERRIDE_CATALOG_PATH", override_path)

    repository = FakeAgentCatalogConfigRepository()
    service = AgentCatalogConfigService(repository)
    _run(
        service.update_override_yaml(
            "agents:\n  - id: reviewer\n    display_name: Reviewer\n    description: Saved in database.\n    runtime: review_runtime"
        )
    )

    config = _run(service.reset_override())

    assert repository.record is None
    assert not override_path.exists()
    assert config.has_override is False


def test_config_service_replace_catalog_persists_structured_payload(tmp_path: Path, monkeypatch):
    default_path = tmp_path / "agents.yaml"
    override_path = tmp_path / "agents.override.yaml"
    default_path.write_text(
        dedent(
            """
            agents:
              - id: reviewer
                display_name: Reviewer
                description: Default reviewer description.
                runtime: review_runtime
            runtimes:
              - key: review_runtime
                task_class: review
                route_profile: implementation
                approval_mode: required
            """
        ).strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(catalog_module, "DEFAULT_CATALOG_PATH", default_path)
    monkeypatch.setattr(catalog_module, "LEGACY_CATALOG_PATH", tmp_path / "agents.json")
    monkeypatch.setattr(catalog_module, "OVERRIDE_CATALOG_PATH", override_path)

    repository = FakeAgentCatalogConfigRepository()
    service = AgentCatalogConfigService(repository)

    catalog = AgentCatalogDefinition.model_validate(
        {
            "agents": [
                {
                    "id": "reviewer",
                    "display_name": "Reviewer",
                    "description": "Structured reviewer description.",
                    "runtime": "review_runtime",
                }
            ],
            "runtimes": [
                {
                    "key": "review_runtime",
                    "task_class": "review",
                    "route_profile": "implementation",
                    "approval_mode": "required",
                }
            ],
        }
    )

    config = _run(service.replace_catalog(catalog))

    assert repository.record is not None
    assert (
        repository.record.override_json["agents"][0]["description"]
        == "Structured reviewer description."
    )
    assert "Structured reviewer description." in (repository.record.override_yaml or "")
    assert override_path.exists()
    assert (
        config.effective_catalog["agents"][0]["description"] == "Structured reviewer description."
    )


def _run(awaitable):
    import asyncio

    return asyncio.run(awaitable)
