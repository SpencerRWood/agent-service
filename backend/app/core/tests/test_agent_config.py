from pathlib import Path

from app.core.agent_config import load_agent_registry


def test_load_agent_registry_from_yaml(tmp_path: Path):
    config_path = tmp_path / "agents.yaml"
    config_path.write_text(
        "\n".join(
            [
                "version: 1",
                "agents:",
                "  worker_b:",
                "    display_name: Worker B",
                "    role: executor",
                "    assigned_to: worker-b",
                "    worker_target: worker_b",
                "    default_provider: codex",
                "providers:",
                "  codex:",
                "    enabled: true",
                "    command: codex --json",
                "    dry_run: false",
                "  copilot_cli:",
                "    enabled: false",
                "    command: copilot",
                "    dry_run: true",
            ]
        )
    )

    registry = load_agent_registry(config_path)

    assert registry.version == 1
    assert registry.get_agent("worker_b").assigned_to == "worker-b"
    assert registry.get_provider("codex").command == "codex --json"
    assert registry.get_provider("codex").dry_run is False
    assert registry.get_provider("copilot_cli").enabled is False


def test_load_agent_registry_returns_empty_registry_when_missing(tmp_path: Path):
    registry = load_agent_registry(tmp_path / "missing.yaml")

    assert registry.agents == {}
    assert registry.providers == {}
