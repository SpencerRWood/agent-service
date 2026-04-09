from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.logging import configure_logging, get_logger, log_request_middleware
from app.core.router_loader import register_feature_routers
from app.core.settings import settings
from app.projections.interaction.app import create_interaction_app

configure_logging(
    level=settings.log_level,
    environment=settings.environment,
    app_name=settings.app_name,
)
logger = get_logger(__name__)
WEB_DIST_DIR = Path("/app/frontend/dist")
WEB_ASSETS_DIR = WEB_DIST_DIR / "assets"


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

    if WEB_ASSETS_DIR.exists():
        app.mount("/assets", StaticFiles(directory=WEB_ASSETS_DIR), name="web-assets")

    @app.get(f"{settings.api_prefix}/")
    def root():
        return {
            "name": settings.app_name,
            "environment": settings.environment,
            "version": settings.app_version,
            "status": "ok",
        }

    if WEB_DIST_DIR.exists():

        @app.get("/", include_in_schema=False)
        def web_root() -> FileResponse:
            return FileResponse(WEB_DIST_DIR / "index.html")

        @app.get("/{full_path:path}", include_in_schema=False)
        def web_spa_fallback(full_path: str) -> FileResponse:
            if full_path.startswith(settings.api_prefix.lstrip("/")):
                raise HTTPException(status_code=404, detail="Not Found")

            requested_path = WEB_DIST_DIR / full_path
            if requested_path.is_file():
                return FileResponse(requested_path)
            return FileResponse(WEB_DIST_DIR / "index.html")

    return app


app = create_app()
