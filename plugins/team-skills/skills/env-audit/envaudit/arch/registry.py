import importlib
import pkgutil
import signal
import threading
import time
from types import ModuleType

from .context import ArchContext
from . import pyast


class _RootBudgetExpired(BaseException):
    pass


def _run_with_timeout(function, actx: ArchContext, timeout: float) -> None:
    if timeout <= 0:
        raise _RootBudgetExpired
    if (
        threading.current_thread() is not threading.main_thread()
        or not hasattr(signal, "setitimer")
    ):
        function(actx)
        return

    def expire(_signum, _frame) -> None:
        raise _RootBudgetExpired

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        function(actx)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            elapsed = time.monotonic() - started
            signal.setitimer(
                signal.ITIMER_REAL,
                max(1e-6, previous_timer[0] - elapsed),
                previous_timer[1],
            )


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
    root_deadline = time.monotonic() + actx.ctx.flags.arch_root_seconds
    try:
        timings = actx.out.setdefault("timings_s", {})
        for check in sorted(checks, key=lambda module: (module.ORDER, module.KEY)):
            started = time.monotonic()
            try:
                _run_with_timeout(
                    check.run,
                    actx,
                    root_deadline - time.monotonic(),
                )
            except _RootBudgetExpired:
                actx.ctx.skip(
                    "architecture", "budget", details=str(actx.root)
                )
                actx.ctx.mark_truncated()
                break
            except Exception as error:
                actx.error(check.KEY, type(error).__name__)
            finally:
                timings[check.KEY] = round(time.monotonic() - started, 2)
    finally:
        pyast._reset_cache(cache_handle)
