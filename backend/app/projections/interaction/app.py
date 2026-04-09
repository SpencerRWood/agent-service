from fastapi import FastAPI

from app.projections.interaction.router import router


def create_interaction_app() -> FastAPI:
    app = FastAPI(
        title="Agent Service Interaction API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.include_router(router)
    return app
