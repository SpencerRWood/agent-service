from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any


class EnrichmentTaskKind(StrEnum):
    RESPONSE = "response"
    TITLE = "title"
    TAGS = "tags"
    FOLLOW_UPS = "follow_ups"


_PARENT_TASK_ID_PATTERN = re.compile(r"Task ID:\s*`?([0-9a-fA-F-]{36})`?")


def classify_prompt_kind(prompt: str) -> EnrichmentTaskKind:
    lowered = prompt.lower()
    if "### task: generate 1-3 broad tags" in lowered:
        return EnrichmentTaskKind.TAGS
    if "### task: generate a concise, 3-5 word title" in lowered:
        return EnrichmentTaskKind.TITLE
    if "### task: suggest 3-5 relevant follow-up questions" in lowered:
        return EnrichmentTaskKind.FOLLOW_UPS
    return EnrichmentTaskKind.RESPONSE


def is_enrichment_task(prompt: str) -> bool:
    return classify_prompt_kind(prompt) != EnrichmentTaskKind.RESPONSE


def extract_parent_task_id(prompt: str) -> str | None:
    match = _PARENT_TASK_ID_PATTERN.search(prompt)
    if match is None:
        return None
    return match.group(1)


def extract_enrichment_payload(kind: EnrichmentTaskKind, content: str | None) -> dict[str, Any]:
    if not content:
        return {}
    parsed = _parse_jsonish(content)
    if not isinstance(parsed, dict):
        return {}
    if kind == EnrichmentTaskKind.TITLE:
        title = parsed.get("title")
        return {"conversation_title": str(title).strip()} if isinstance(title, str) else {}
    if kind == EnrichmentTaskKind.TAGS:
        tags = parsed.get("tags")
        if isinstance(tags, list):
            return {"conversation_tags": [str(tag).strip() for tag in tags if str(tag).strip()]}
        return {}
    if kind == EnrichmentTaskKind.FOLLOW_UPS:
        follow_ups = parsed.get("follow_ups")
        if isinstance(follow_ups, list):
            return {"follow_ups": [str(item).strip() for item in follow_ups if str(item).strip()]}
        return {}
    return {}


def _parse_jsonish(content: str) -> Any:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None
