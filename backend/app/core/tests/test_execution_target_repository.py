from app.platform.execution_targets.repository import _supports_tool


def test_supports_tool_matches_explicit_tool():
    assert _supports_tool(["agent.execute_coding_task"], "agent.execute_coding_task") is True


def test_supports_tool_matches_wildcard():
    assert _supports_tool(["*"], "rag.promote_artifact") is True


def test_supports_tool_rejects_unknown_tool_without_wildcard():
    assert _supports_tool(["agent.execute_coding_task"], "rag.promote_artifact") is False
