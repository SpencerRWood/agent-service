import sys
from pathlib import Path


def to_pascal_case(name: str) -> str:
    return "".join(word.capitalize() for word in name.split("_"))


TEMPLATE_ROUTER = """from fastapi import APIRouter
from .service import {class_name}Service

router = APIRouter(prefix="/{name}", tags=["{name}"])


@router.get("/")
def get_{name}():
    return {class_name}Service().get()
"""


TEMPLATE_SERVICE = """class {class_name}Service:

    def get(self):
        return {{"message": "{name} endpoint"}}
"""


TEMPLATE_SCHEMAS = """from pydantic import BaseModel


class {class_name}Response(BaseModel):
    message: str
"""


TEMPLATE_INIT = ""


TEMPLATE_CONFTST = """import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.features.{name}.router import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)
"""


TEMPLATE_ROUTER_TEST = """def test_{name}_endpoint(client):

    response = client.get("/{name}/")

    assert response.status_code == 200
    assert response.json()["message"] == "{name} endpoint"
"""


TEMPLATE_SERVICE_TEST = """from app.features.{name}.service import {class_name}Service


def test_service_get():

    service = {class_name}Service()

    result = service.get()

    assert result["message"] == "{name} endpoint"
"""


def main():

    if len(sys.argv) < 2:
        print("Usage: python scripts/create_feature.py <feature_name>")
        sys.exit(1)

    feature_name = sys.argv[1]
    class_name = to_pascal_case(feature_name)

    root = Path(__file__).resolve().parents[1]

    backend_features_dir = root / "backend" / "app" / "features"
    feature_dir = backend_features_dir / feature_name

    if feature_dir.exists():
        print(f"Feature '{feature_name}' already exists.")
        sys.exit(1)

    backend_features_dir.mkdir(parents=True, exist_ok=True)

    features_init = backend_features_dir / "__init__.py"
    if not features_init.exists():
        features_init.write_text("")

    feature_dir.mkdir()

    (feature_dir / "router.py").write_text(
        TEMPLATE_ROUTER.format(name=feature_name, class_name=class_name)
    )

    (feature_dir / "service.py").write_text(
        TEMPLATE_SERVICE.format(name=feature_name, class_name=class_name)
    )

    (feature_dir / "schemas.py").write_text(
        TEMPLATE_SCHEMAS.format(class_name=class_name)
    )

    (feature_dir / "__init__.py").write_text(TEMPLATE_INIT)

    # tests
    tests_dir = feature_dir / "tests"
    tests_dir.mkdir()

    (tests_dir / "__init__.py").write_text("")

    (tests_dir / "conftest.py").write_text(
        TEMPLATE_CONFTST.format(name=feature_name)
    )

    (tests_dir / "test_router.py").write_text(
        TEMPLATE_ROUTER_TEST.format(name=feature_name)
    )

    (tests_dir / "test_service.py").write_text(
        TEMPLATE_SERVICE_TEST.format(name=feature_name, class_name=class_name)
    )

    print(f"Created backend feature '{feature_name}' with tests.")


if __name__ == "__main__":
    main()
