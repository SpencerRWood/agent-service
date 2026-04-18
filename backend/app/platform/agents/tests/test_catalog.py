from pathlib import Path
from textwrap import dedent

from app.platform.agents import catalog as catalog_module
from app.platform.agents.catalog import (
    delete_agent_catalog_override,
    load_agent_catalog,
    load_effective_catalog_payload,
    save_agent_catalog_override_payload,
)
from app.platform.agents.service import AgentRegistry, RuntimeRegistry


def test_load_agent_catalog_from_json_config(tmp_path: Path):
    catalog_path = tmp_path / "agents.yaml"
    catalog_path.write_text(
        dedent(
            """
        agents:
          - id: architect
            display_name: Architect
            description: Plans system changes.
            supports_streaming: true
            system_prompt: Think in systems.
            workflow:
              goal: Drive the review loop.
              entry_step: inspect
              steps:
                - id: inspect
                  instructions: Inspect the repository before responding.
                  on_success:
                    action: finish
            runtime: planning_runtime
        runtimes:
          - key: planning_runtime
            task_class: plan_only
            route_profile: cheap
            approval_mode: none
            prompt_preamble: Think in systems.
        """
        ).strip(),
        encoding="utf-8",
    )

    catalog = load_agent_catalog(catalog_path)

    assert [agent.id for agent in catalog.agents] == ["architect"]
    assert catalog.agents[0].system_prompt == "Think in systems."
    assert catalog.agents[0].workflow is not None
    assert catalog.agents[0].workflow.entry_step == "inspect"
    assert catalog.agents[0].workflow.steps[0].on_success is not None
    assert catalog.runtimes[0].key == "planning_runtime"


def test_load_agent_catalog_falls_back_when_config_missing(tmp_path: Path):
    catalog = load_agent_catalog(tmp_path / "missing.json")

    assert [agent.id for agent in catalog.agents] == [
        "planner",
        "rag-analyst",
        "coder",
        "reviewer",
    ]


def test_load_agent_catalog_falls_back_when_runtime_reference_is_invalid(tmp_path: Path):
    catalog_path = tmp_path / "agents.yaml"
    catalog_path.write_text(
        dedent(
            """
        agents:
          - id: architect
            display_name: Architect
            description: Plans system changes.
            runtime: missing_runtime
        runtimes: []
        """
        ).strip(),
        encoding="utf-8",
    )

    catalog = load_agent_catalog(catalog_path)

    assert [agent.id for agent in catalog.agents] == [
        "planner",
        "rag-analyst",
        "coder",
        "reviewer",
    ]


def test_agent_registry_derives_requires_approval_from_runtime():
    catalog = load_agent_catalog()
    runtime_registry = RuntimeRegistry(catalog.runtimes)
    agent_registry = AgentRegistry(runtime_registry, catalog.agents)

    reviewer = agent_registry.get_agent("reviewer")
    coder = agent_registry.get_agent("coder")

    assert reviewer.requires_approval is True
    assert coder.requires_approval is False
    assert reviewer.workflow is not None
    assert reviewer.workflow.entry_step == "review"
    assert reviewer.workflow.steps[0].on_needs_changes is not None
    assert reviewer.workflow.steps[0].on_needs_changes.to == "coder"


def test_effective_catalog_merges_override_on_top_of_default(tmp_path: Path, monkeypatch):
    default_path = tmp_path / "agents.yaml"
    override_path = tmp_path / "agents.override.yaml"
    default_path.write_text(
        dedent(
            """
            agents:
              - id: reviewer
                display_name: Reviewer
                description: Default description.
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

    save_agent_catalog_override_payload(
        {
            "agents": [
                {
                    "id": "reviewer",
                    "display_name": "Reviewer",
                    "description": "Override description.",
                    "runtime": "review_runtime",
                }
            ]
        }
    )

    payload = load_effective_catalog_payload()

    assert payload["agents"][0]["description"] == "Override description."
    delete_agent_catalog_override()
    assert not override_path.exists()
