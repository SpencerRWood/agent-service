from fastapi import APIRouter

from .schemas import HealthResponse
from .service import HealthService

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/", response_model=HealthResponse)
def get_health() -> HealthResponse:
    return HealthService().get()
