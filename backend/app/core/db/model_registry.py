import importlib
import pkgutil


def import_feature_models() -> None:
    """Import any feature models modules so Base.metadata is populated."""
    package_name = "app.features"
    package = importlib.import_module(package_name)

    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        models_module = f"{package_name}.{module_name}.models"

        try:
            importlib.import_module(models_module)
        except ModuleNotFoundError as exc:
            if exc.name != models_module:
                raise


import_feature_models()
