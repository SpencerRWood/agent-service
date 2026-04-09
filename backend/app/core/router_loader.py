import importlib
import pkgutil

from fastapi import FastAPI
from fastapi.routing import APIRouter

from app.core.settings import settings


def register_feature_routers(app: FastAPI) -> None:
    """Automatically discover and register routers from app.features.* and app.platform.*."""
    for package_name in ("app.features", "app.platform"):
        package = importlib.import_module(package_name)

        for _, module_name, _ in pkgutil.iter_modules(package.__path__):
            router_module_name = f"{package_name}.{module_name}.router"

            try:
                module = importlib.import_module(router_module_name)
            except ModuleNotFoundError as exc:
                if exc.name != router_module_name:
                    raise
                continue

            for attribute_name in ("router", "tool_router", "webhook_router"):
                candidate = getattr(module, attribute_name, None)
                if isinstance(candidate, APIRouter):
                    app.include_router(candidate, prefix=settings.api_prefix)
