import importlib
import pkgutil

from fastapi import FastAPI

from app.core.settings import settings


def register_feature_routers(app: FastAPI) -> None:
    """Automatically discover and register routers from app.features.*."""
    package_name = "app.features"
    package = importlib.import_module(package_name)

    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        router_module_name = f"{package_name}.{module_name}.router"

        try:
            module = importlib.import_module(router_module_name)
        except ModuleNotFoundError as exc:
            if exc.name != router_module_name:
                raise
            continue

        router = getattr(module, "router", None)
        if router is not None:
            app.include_router(router, prefix=settings.api_prefix)
