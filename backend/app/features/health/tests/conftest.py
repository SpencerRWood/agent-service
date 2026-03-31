import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.features.health.router import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)
