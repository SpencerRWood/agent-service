from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

import httpx

from app.core.settings import settings

REQUIRED_OPERATIONS = {
    ("/approvals/", "post", "ApprovalItemCreate", "ApprovalItemRead"),
    ("/approvals/", "get", None, "ApprovalItemRead"),
    ("/approvals/{item_id}", "get", None, "ApprovalItemRead"),
    ("/approvals/{item_id}/approve", "post", "ApprovalItemApprove", "ApprovalItemRead"),
    ("/approvals/{item_id}/reject", "post", "ApprovalItemReject", "ApprovalItemRead"),
}


class ControlHubContractError(RuntimeError):
    """Raised when the Control Hub contract does not match what this service consumes."""


class ControlHubSchemaModel(Mapping[str, Any]):
    schema_name: ClassVar[str]

    def __init__(self, payload: Mapping[str, Any] | None = None, /, **kwargs: Any) -> None:
        data = dict(payload or {})
        if kwargs:
            data.update(kwargs)
        get_control_hub_contract().validate_schema(self.schema_name, data)
        self._data = data

    @classmethod
    def model_validate(cls, payload: Mapping[str, Any]) -> ControlHubSchemaModel:
        return cls(payload)

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        del mode
        return dict(self._data)

    def model_copy(self, *, update: Mapping[str, Any] | None = None) -> ControlHubSchemaModel:
        data = self.model_dump()
        if update:
            data.update(update)
        return type(self)(data)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __getattr__(self, key: str) -> Any:
        try:
            return self._data[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


class ControlHubApprovalItemCreate(ControlHubSchemaModel):
    schema_name = "ApprovalItemCreate"


class ControlHubApprovalItemRead(ControlHubSchemaModel):
    schema_name = "ApprovalItemRead"


class ControlHubApprovalItemApprove(ControlHubSchemaModel):
    schema_name = "ApprovalItemApprove"


class ControlHubApprovalItemReject(ControlHubSchemaModel):
    schema_name = "ApprovalItemReject"


class ControlHubContract:
    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document = dict(document)

    def get_schema(self, schema_name: str) -> dict[str, Any]:
        schemas = self.document.get("components", {}).get("schemas", {})
        schema = schemas.get(schema_name)
        if not isinstance(schema, dict):
            raise ControlHubContractError(
                f"Schema '{schema_name}' was not found in Control Hub contract."
            )
        return schema

    def validate_schema(self, schema_name: str, payload: Mapping[str, Any]) -> None:
        _validate_schema(
            schema=self.get_schema(schema_name),
            instance=payload,
            contract=self.document,
            path=schema_name,
        )

    def assert_compatible(self) -> None:
        paths = self.document.get("paths", {})
        schemas = self.document.get("components", {}).get("schemas", {})
        if not isinstance(paths, dict) or not isinstance(schemas, dict):
            raise ControlHubContractError(
                "Control Hub contract is missing paths or components.schemas."
            )

        missing_schemas = sorted(
            {
                "ApprovalItemCreate",
                "ApprovalItemRead",
                "ApprovalItemApprove",
                "ApprovalItemReject",
                "ApprovalStatus",
            }
            - set(schemas)
        )
        missing_operations: list[str] = []
        for path, method, request_schema, response_schema in REQUIRED_OPERATIONS:
            path_item = paths.get(path)
            if not isinstance(path_item, dict):
                missing_operations.append(f"{method.upper()} {path}")
                continue

            operation = path_item.get(method)
            if not isinstance(operation, dict):
                missing_operations.append(f"{method.upper()} {path}")
                continue

            if request_schema is not None:
                actual_request_schema = _resolve_request_schema_name(operation)
                if actual_request_schema != request_schema:
                    raise ControlHubContractError(
                        f"{method.upper()} {path} expected request schema '{request_schema}' "
                        f"but found '{actual_request_schema}'."
                    )

            actual_response_schema = _resolve_response_schema_name(operation)
            if actual_response_schema != response_schema:
                raise ControlHubContractError(
                    f"{method.upper()} {path} expected response schema '{response_schema}' "
                    f"but found '{actual_response_schema}'."
                )

        if missing_schemas or missing_operations:
            details: list[str] = []
            if missing_operations:
                details.append(f"missing operations: {', '.join(missing_operations)}")
            if missing_schemas:
                details.append(f"missing schemas: {', '.join(missing_schemas)}")
            raise ControlHubContractError(
                "Control Hub contract is incompatible: " + "; ".join(details)
            )


def load_contract_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ControlHubContractError(f"Control Hub contract file not found at '{path}'.")
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def get_control_hub_contract() -> ControlHubContract:
    return ControlHubContract(load_contract_document(settings.resolved_control_hub_contract_path))


def build_contract_enum(schema_name: str) -> type[StrEnum]:
    schema = get_control_hub_contract().get_schema(schema_name)
    values = schema.get("enum")
    if not isinstance(values, list) or not values:
        raise ControlHubContractError(f"Schema '{schema_name}' does not define an enum.")
    return StrEnum(schema_name, {str(value): str(value) for value in values})


ApprovalStatus = build_contract_enum("ApprovalStatus")


def assert_local_contract_compatible() -> None:
    get_control_hub_contract().assert_compatible()


def assert_contract_documents_compatible(document: dict[str, Any]) -> None:
    ControlHubContract(document).assert_compatible()


async def validate_remote_openapi_if_enabled() -> None:
    if not settings.control_hub_enable_remote_schema_check:
        return

    async with httpx.AsyncClient(timeout=settings.control_hub_timeout_seconds) as client:
        response = await client.get(settings.control_hub_openapi_url)
        response.raise_for_status()
        assert_contract_documents_compatible(response.json())


def _resolve_request_schema_name(operation: Mapping[str, Any]) -> str | None:
    content = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
    schema = content.get("schema")
    if not isinstance(schema, Mapping):
        return None
    return _schema_name(schema)


def _resolve_response_schema_name(operation: Mapping[str, Any]) -> str | None:
    responses = operation.get("responses", {})
    if not isinstance(responses, Mapping):
        return None
    for status_code in ("200", "201"):
        response = responses.get(status_code)
        if not isinstance(response, Mapping):
            continue
        schema = response.get("content", {}).get("application/json", {}).get("schema")
        if not isinstance(schema, Mapping):
            continue
        if schema.get("type") == "array":
            items = schema.get("items")
            if not isinstance(items, Mapping):
                return None
            return _schema_name(items)
        return _schema_name(schema)
    return None


def _schema_name(schema: Mapping[str, Any]) -> str | None:
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        return ref.rsplit("/", 1)[-1]
    return None


def _validate_schema(
    *,
    schema: Mapping[str, Any],
    instance: Any,
    contract: Mapping[str, Any],
    path: str,
) -> None:
    ref = schema.get("$ref")
    if isinstance(ref, str):
        _validate_schema(
            schema=_resolve_ref(contract, ref),
            instance=instance,
            contract=contract,
            path=path,
        )
        return

    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        errors: list[str] = []
        for candidate in any_of:
            if not isinstance(candidate, Mapping):
                continue
            try:
                _validate_schema(schema=candidate, instance=instance, contract=contract, path=path)
                return
            except ControlHubContractError as exc:
                errors.append(str(exc))
        raise ControlHubContractError(
            f"{path} did not match any allowed schema variant: {'; '.join(errors)}"
        )

    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(instance, Mapping):
            raise ControlHubContractError(f"{path} must be an object.")

        required = schema.get("required", [])
        if isinstance(required, list):
            missing = [key for key in required if key not in instance]
            if missing:
                raise ControlHubContractError(
                    f"{path} is missing required fields: {', '.join(missing)}"
                )

        properties = schema.get("properties", {})
        additional_properties = schema.get("additionalProperties", False)
        if not isinstance(properties, Mapping):
            properties = {}

        for key, value in instance.items():
            property_schema = properties.get(key)
            if isinstance(property_schema, Mapping):
                _validate_schema(
                    schema=property_schema,
                    instance=value,
                    contract=contract,
                    path=f"{path}.{key}",
                )
                continue

            if additional_properties is True:
                continue
            if isinstance(additional_properties, Mapping):
                _validate_schema(
                    schema=additional_properties,
                    instance=value,
                    contract=contract,
                    path=f"{path}.{key}",
                )
                continue

            raise ControlHubContractError(
                f"{path}.{key} is not declared in the Control Hub contract."
            )

        return

    if schema_type == "array":
        if not isinstance(instance, list):
            raise ControlHubContractError(f"{path} must be an array.")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(instance):
                _validate_schema(
                    schema=item_schema,
                    instance=item,
                    contract=contract,
                    path=f"{path}[{index}]",
                )
        return

    if schema_type == "string":
        if not isinstance(instance, str):
            raise ControlHubContractError(f"{path} must be a string.")
        return

    if schema_type == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            raise ControlHubContractError(f"{path} must be an integer.")
        return

    if schema_type == "boolean":
        if not isinstance(instance, bool):
            raise ControlHubContractError(f"{path} must be a boolean.")
        return

    if schema_type == "null":
        if instance is not None:
            raise ControlHubContractError(f"{path} must be null.")
        return

    if schema_type is None:
        return

    raise ControlHubContractError(f"{path} uses unsupported schema type '{schema_type}'.")


def _resolve_ref(contract: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise ControlHubContractError(f"Unsupported external reference '{ref}'.")

    node: Any = contract
    for part in ref.removeprefix("#/").split("/"):
        if not isinstance(node, Mapping) or part not in node:
            raise ControlHubContractError(f"Unable to resolve contract reference '{ref}'.")
        node = node[part]

    if not isinstance(node, Mapping):
        raise ControlHubContractError(
            f"Contract reference '{ref}' did not resolve to an object schema."
        )
    return node
