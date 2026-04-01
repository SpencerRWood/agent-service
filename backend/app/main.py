from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.router_loader import register_feature_routers
from app.core.settings import settings
from app.integrations.control_hub.contract import (
    assert_local_snapshot_compatible,
    validate_remote_openapi_if_enabled,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    assert_local_snapshot_compatible()
    await validate_remote_openapi_if_enabled()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_feature_routers(app)

    @app.get("/")
    def root():
        return {
            "name": settings.app_name,
            "environment": settings.environment,
            "version": settings.app_version,
            "status": "ok",
        }

    return app


app = create_app()
