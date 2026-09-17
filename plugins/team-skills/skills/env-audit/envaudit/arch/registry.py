import importlib
import pkgutil
from types import ModuleType

from .context import ArchContext
from . import pyast


def discover_checks() -> list[ModuleType]:
    package = importlib.import_module("envaudit.arch.checks")
    modules = []
    for module_info in pkgutil.iter_modules(
        package.__path__, f"{package.__name__}."
    ):
        module = importlib.import_module(module_info.name)
        if all(hasattr(module, name) for name in ("KEY", "ORDER", "run")):
            modules.append(module)
    return sorted(modules, key=lambda module: (module.ORDER, module.KEY))


def run_checks(actx: ArchContext, checks: list[ModuleType]) -> None:
    cache_handle = pyast._set_cache(actx.cache)
    try:
        for check in sorted(checks, key=lambda module: (module.ORDER, module.KEY)):
            try:
                check.run(actx)
            except Exception as error:
                actx.error(check.KEY, type(error).__name__)
    finally:
        pyast._reset_cache(cache_handle)
