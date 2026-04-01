from __future__ import annotations

import json

import pytest

from app.integrations.control_hub.contract import (
    ControlHubApprovalItemCreate,
    ControlHubContract,
    ControlHubContractError,
)


def build_contract_document() -> dict:
    return {
        "openapi": "3.1.0",
        "paths": {
            "/approvals/": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ApprovalItemCreate"}
                            }
                        }
                    },
                    "responses": {
                        "201": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ApprovalItemRead"}
                                }
                            }
                        }
                    },
                },
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/ApprovalItemRead"},
                                    }
                                }
                            }
                        }
                    }
                },
            },
            "/approvals/{item_id}": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ApprovalItemRead"}
                                }
                            }
                        }
                    }
                }
            },
            "/approvals/{item_id}/approve": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ApprovalItemApprove"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ApprovalItemRead"}
                                }
                            }
                        }
                    },
                }
            },
            "/approvals/{item_id}/reject": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ApprovalItemReject"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ApprovalItemRead"}
                                }
                            }
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "ApprovalStatus": {"type": "string", "enum": ["PENDING", "APPROVED", "REJECTED"]},
                "ApprovalItemCreate": {
                    "type": "object",
                    "required": ["title", "action_type", "requested_by"],
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "action_type": {"type": "string"},
                        "payload_json": {"type": "object", "additionalProperties": True},
                        "requested_by": {"type": "string"},
                        "assigned_to": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    },
                },
                "ApprovalItemRead": {
                    "type": "object",
                    "required": [
                        "id",
                        "title",
                        "action_type",
                        "payload_json",
                        "status",
                        "requested_by",
                        "created_at",
                        "updated_at",
                    ],
                    "properties": {
                        "id": {"type": "integer"},
                        "title": {"type": "string"},
                        "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "action_type": {"type": "string"},
                        "payload_json": {"type": "object", "additionalProperties": True},
                        "status": {"$ref": "#/components/schemas/ApprovalStatus"},
                        "requested_by": {"type": "string"},
                        "assigned_to": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "created_at": {"type": "string"},
                        "updated_at": {"type": "string"},
                        "decided_at": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "decided_by": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "decision_reason": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    },
                },
                "ApprovalItemApprove": {
                    "type": "object",
                    "required": ["decided_by"],
                    "properties": {
                        "decided_by": {"type": "string"},
                        "decision_reason": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    },
                },
                "ApprovalItemReject": {
                    "type": "object",
                    "required": ["decided_by", "decision_reason"],
                    "properties": {
                        "decided_by": {"type": "string"},
                        "decision_reason": {"type": "string"},
                    },
                },
            }
        },
    }


def test_contract_asserts_required_operations():
    contract = ControlHubContract(build_contract_document())
    contract.assert_compatible()


def test_schema_backed_models_reject_undeclared_fields(monkeypatch):
    monkeypatch.setattr(
        "app.integrations.control_hub.contract.get_control_hub_contract",
        lambda: ControlHubContract(build_contract_document()),
    )

    with pytest.raises(ControlHubContractError):
        ControlHubApprovalItemCreate(
            title="Approve task",
            action_type="code_change",
            requested_by="agent-a",
            unknown_field="oops",
        )


def test_schema_backed_models_preserve_payload_shape(monkeypatch):
    monkeypatch.setattr(
        "app.integrations.control_hub.contract.get_control_hub_contract",
        lambda: ControlHubContract(build_contract_document()),
    )

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
        "payload_json": {"repo": "agent-service"},
    }
