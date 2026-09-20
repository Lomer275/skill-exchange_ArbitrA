import signal
import threading
import time
from types import ModuleType

from .context import Context


SECTION_WEIGHTS = {
    "secrets": 3,
    "architecture": 3,
    "instructions": 2,
    "handoff": 2,
    "skills": 2,
    "tokens": 2,
}
MIN_ROOT_SECONDS = 3.0
# Root timeouts return partial documents and need a moment to unwind.
ARCHITECTURE_RETURN_GRACE_SECONDS = 0.1


class _SectionBudgetExpired(BaseException):
    pass


def _weight(module: ModuleType) -> int:
    return SECTION_WEIGHTS.get(module.NAME, 1)


def allocate_root_budget(
    section_remaining: float,
    roots_remaining: int,
    root_cap: float,
    min_root_seconds: float = MIN_ROOT_SECONDS,
) -> float:
    if roots_remaining <= 0 or root_cap <= 0 or section_remaining <= 0:
        return 0.0
    fair_share = section_remaining / roots_remaining
    reserve_per_root = min(min_root_seconds, fair_share)
    reserve = reserve_per_root * (roots_remaining - 1)
    return min(root_cap, max(0.0, section_remaining - reserve))


def _run_with_timeout(function, timeout: float):
    if timeout <= 0:
        raise _SectionBudgetExpired
    if (
        threading.current_thread() is not threading.main_thread()
        or not hasattr(signal, "setitimer")
    ):
        return function()

    def expire(_signum, _frame) -> None:
        raise _SectionBudgetExpired

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        return function()
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


def _skip_budget(ctx: Context, section: str) -> None:
    expected = {"section": section, "reason": "budget", "details": None}
    if expected not in ctx.skipped:
        ctx.skip(section, "budget")
    ctx.mark_truncated()


def run_sections(
    ctx: Context, modules: list[ModuleType]
) -> tuple[dict[str, dict | None], dict[str, float]]:
    ordered = sorted(modules, key=lambda item: (item.ORDER, item.NAME))
    enabled = [
        module
        for module in ordered
        if not ctx.flags.only or module.NAME in ctx.flags.only
    ]
    remaining_weight = sum(_weight(module) for module in enabled)
    sections: dict[str, dict | None] = {}
    durations: dict[str, float] = {}

    for module in ordered:
        if module not in enabled:
            ctx.skip(module.NAME, "flag_off")
            sections[module.NAME] = None
            continue

        weight = _weight(module)
        started = time.perf_counter()
        remaining = max(0.0, ctx.deadline - time.time())
        section_budget = (
            remaining * weight / remaining_weight
            if remaining_weight > 0
            else 0.0
        )
        ctx.section_budget_seconds = section_budget
        ctx.section_deadline = min(ctx.deadline, time.time() + section_budget)
        try:
            if section_budget <= 0:
                raise _SectionBudgetExpired
            try:
                sections[module.NAME] = _run_with_timeout(
                    lambda: module.collect(ctx),
                    section_budget
                    + (
                        ARCHITECTURE_RETURN_GRACE_SECONDS
                        if module.NAME == "architecture"
                        else 0.0
                    ),
                )
            except Exception as error:
                ctx.error(module.NAME, type(error).__name__)
                sections[module.NAME] = None
            if ctx.expired():
                _skip_budget(ctx, module.NAME)
        except _SectionBudgetExpired:
            _skip_budget(ctx, module.NAME)
            sections[module.NAME] = None
        finally:
            durations[module.NAME] = round(
                time.perf_counter() - started, 6
            )
            ctx.section_deadline = None
            ctx.section_budget_seconds = None
            remaining_weight -= weight

    return sections, durations
