from __future__ import annotations

import json

import pytest

from app.integrations.control_hub.contract import (
    ApprovalStatus,
    ControlHubApprovalItemCreate,
    ControlHubApprovalItemRead,
    ControlHubContractError,
)


def test_models_reject_undeclared_fields():
    with pytest.raises(ControlHubContractError):
        ControlHubApprovalItemCreate.model_validate(
            {
                "title": "Approve task",
                "action_type": "code_change",
                "requested_by": "agent-a",
                "unknown_field": "oops",
            }
        )


def test_models_preserve_payload_shape():
    item = ControlHubApprovalItemCreate(
        title="Approve task",
        action_type="code_change",
        requested_by="agent-a",
        payload_json={"repo": "agent-service"},
    )

    assert json.loads(json.dumps(item.model_dump(mode="json"))) == {
        "title": "Approve task",
        "action_type": "code_change",
        "requested_by": "agent-a",
        "description": None,
        "payload_json": {"repo": "agent-service"},
        "assigned_to": None,
    }


def test_read_model_coerces_status_enum():
    item = ControlHubApprovalItemRead(
        id=1,
        title="Approve task",
        action_type="code_change",
        payload_json={"repo": "agent-service"},
        status="PENDING",
        requested_by="agent-a",
        created_at="2026-04-09T12:00:00Z",
        updated_at="2026-04-09T12:00:00Z",
    )

    assert item.status == ApprovalStatus.PENDING


def test_model_copy_revalidates_updates():
    item = ControlHubApprovalItemRead(
        id=1,
        title="Approve task",
        action_type="code_change",
        payload_json={"repo": "agent-service"},
        status="PENDING",
        requested_by="agent-a",
        created_at="2026-04-09T12:00:00Z",
        updated_at="2026-04-09T12:00:00Z",
    )

    with pytest.raises(ControlHubContractError):
        item.model_copy(update={"status": "BROKEN"})
