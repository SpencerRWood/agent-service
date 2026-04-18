from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.settings import settings
from app.platform.agents.router import (
    get_agent_catalog_config_service,
    router,
)
from app.platform.agents.schemas import AgentCatalogConfigRead


class FakeAgentCatalogConfigService:
    def __init__(self) -> None:
        self.saved_yaml: str | None = None
        self.reset_called = False

    async def get_config(self) -> AgentCatalogConfigRead:
        return _build_config_read(
            override_yaml=self.saved_yaml,
            effective_yaml=self.saved_yaml or "default: true\n",
            has_override=self.saved_yaml is not None,
        )

    async def update_override_yaml(self, yaml_text: str) -> AgentCatalogConfigRead:
        self.saved_yaml = yaml_text.strip() or None
        return await self.get_config()

    async def reset_override(self) -> AgentCatalogConfigRead:
        self.reset_called = True
        self.saved_yaml = None
        return await self.get_config()


def build_client() -> TestClient:
    app = FastAPI()
    service = FakeAgentCatalogConfigService()
    app.include_router(router, prefix=settings.api_prefix)
    app.dependency_overrides[get_agent_catalog_config_service] = lambda: service
    app.state.fake_agent_catalog_config_service = service
    return TestClient(app)


def test_get_agent_config_returns_config_payload():
    client = build_client()

    response = client.get("/api/platform/agents/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_override"] is False
    assert payload["default_yaml"] == "default: true\n"


def test_put_agent_config_override_updates_saved_yaml():
    client = build_client()

    response = client.put(
        "/api/platform/agents/config/override",
        json={"yaml": "agents:\n  - id: reviewer\n"},
    )

    assert response.status_code == 200
    assert (
        client.app.state.fake_agent_catalog_config_service.saved_yaml == "agents:\n  - id: reviewer"
    )
    assert response.json()["has_override"] is True


def test_delete_agent_config_override_resets_state():
    client = build_client()
    client.put("/api/platform/agents/config/override", json={"yaml": "agents:\n  - id: reviewer\n"})

    response = client.delete("/api/platform/agents/config/override")

    assert response.status_code == 200
    assert client.app.state.fake_agent_catalog_config_service.reset_called is True
    assert response.json()["has_override"] is False


def _build_config_read(
    *,
    override_yaml: str | None,
    effective_yaml: str,
    has_override: bool,
) -> AgentCatalogConfigRead:
    return AgentCatalogConfigRead(
        default_path="backend/config/agents.yaml",
        override_path="backend/config/agents.override.yaml",
        has_override=has_override,
        default_yaml="default: true\n",
        override_yaml=override_yaml,
        effective_yaml=effective_yaml,
        default_catalog={"default": True},
        override_catalog={"saved": True} if has_override else None,
        effective_catalog={"effective": True},
    )
