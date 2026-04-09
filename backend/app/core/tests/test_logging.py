from __future__ import annotations

import json
import logging

from app.core.logging import JsonFormatter


def test_json_formatter_includes_standard_and_extra_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=12,
        msg="hello world",
        args=(),
        exc_info=None,
    )
    record.event = "test_event"
    record.repo = "agent-service"
    record.duration_ms = 12.5

    payload = json.loads(formatter.format(record))

    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["event"] == "test_event"
    assert payload["repo"] == "agent-service"
    assert payload["duration_ms"] == 12.5
    assert "timestamp" in payload
