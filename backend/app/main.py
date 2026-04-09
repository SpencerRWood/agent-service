from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.logging import configure_logging, get_logger, log_request_middleware
from app.core.router_loader import register_feature_routers
from app.core.settings import settings
from app.integrations.control_hub.contract import (
    assert_local_contract_compatible,
    validate_remote_openapi_if_enabled,
)
from app.projections.interaction.app import create_interaction_app

configure_logging(
    level=settings.log_level,
    environment=settings.environment,
    app_name=settings.app_name,
)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "Application startup",
        extra={
            "event": "application_startup",
            "environment": settings.environment,
            "version": settings.app_version,
        },
    )
    assert_local_contract_compatible()
    await validate_remote_openapi_if_enabled()
    yield
    logger.info(
        "Application shutdown",
        extra={
            "event": "application_shutdown",
            "environment": settings.environment,
            "version": settings.app_version,
        },
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=f"{settings.api_prefix}/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(log_request_middleware)

    register_feature_routers(app)
    app.mount(f"{settings.api_prefix}/interaction", create_interaction_app())

    @app.get(f"{settings.api_prefix}/")
    def root():
        return {
            "name": settings.app_name,
            "environment": settings.environment,
            "version": settings.app_version,
            "status": "ok",
        }

    return app


app = create_app()
