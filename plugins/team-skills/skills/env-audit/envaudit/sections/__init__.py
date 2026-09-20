import importlib
import pkgutil
import time
from types import ModuleType

from envaudit.core.context import Context


def discover() -> list[ModuleType]:
    modules = []
    for module_info in pkgutil.iter_modules(__path__, f"{__name__}."):
        module = importlib.import_module(module_info.name)
        if all(hasattr(module, attribute) for attribute in ("NAME", "ORDER", "collect")):
            modules.append(module)
    return sorted(modules, key=lambda module: (module.ORDER, module.NAME))


def run_sections(
    ctx: Context, modules: list[ModuleType]
) -> tuple[dict[str, dict | None], dict[str, float]]:
    sections: dict[str, dict | None] = {}
    durations: dict[str, float] = {}
    for module in sorted(modules, key=lambda item: (item.ORDER, item.NAME)):
        started = time.perf_counter()
        if ctx.flags.only and module.NAME not in ctx.flags.only:
            ctx.skip(module.NAME, "flag_off")
            sections[module.NAME] = None
        elif ctx.expired():
            ctx.skip(module.NAME, "budget")
            ctx.mark_truncated()
            sections[module.NAME] = None
        else:
            try:
                sections[module.NAME] = module.collect(ctx)
            except Exception as error:
                ctx.error(module.NAME, type(error).__name__)
                sections[module.NAME] = None
        durations[module.NAME] = round(time.perf_counter() - started, 6)
    return sections, durations
