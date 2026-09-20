from pathlib import Path
import shutil
import time

from envaudit import DEFINITIONS_VERSION
from envaudit.arch.context import ArchContext
from envaudit.arch.registry import (
    _RootBudgetExpired,
    _run_with_timeout,
    discover_checks,
    run_checks,
)
from envaudit.core.context import Context
from envaudit.core.runner import is_git_repo


NAME = "architecture"
ORDER = 80

DEFINITIONS = {
    "lines": "number of newline bytes plus one for a non-terminated final line",
    "sloc": "lines excluding blank lines and line comments",
    "sloc_no_strings": "sloc excluding lines inside multiline Python literals",
    "prod_scope": "code outside tests, migrations, virtualenvs, node_modules, build, and dist",
    "third_party_import": "top-level name outside sys.stdlib_module_names and local modules",
    "edge": "a static import between local modules",
    "edge_level": "module, top-package, or second-package aggregation of an edge",
    "edge_flags": "type-checking, function-local, lazy, and test/prod edge attributes",
    "scc": "a Tarjan component containing at least two nodes",
    "fan_in": "distinct production importers excluding type-checking imports",
    "orphan": "a module outside runtime and framework auto-discovery closures",
    "interface_module": "a module that separates runtime code from an external client",
    "live_unit": "a current-user cron or systemd unit whose resolved paths intersect the root",
    "outside_git": "a file absent from HEAD and every remote ref",
    "local_only": "a branch head absent from every remote ref",
    "fake_value": "a deterministic placeholder-value filter",
    "dated_name": "a filename containing a valid YYYYMMDD-like date",
    "data_shaped": "at least 80 percent literal lines, sampled for files from 2 to 20 MB",
    "distinct_values": "distinct matches counted in memory without emitting values",
    "stdlib_io": "stdlib modules that perform external I/O",
    "io_builtin": "built-in calls that perform external I/O",
    "dist_alias_table": "manifest distribution names mapped to import names",
}


def _document() -> dict:
    rule_inputs: dict[str, dict] = {}
    return {
        "schema": "env-audit/arch",
        "definitions_version": DEFINITIONS_VERSION,
        "definitions": dict(DEFINITIONS),
        "rule_inputs": rule_inputs,
        "blind_spots": [],
    }


def _cleanup(actx: ArchContext) -> None:
    paths = actx.cache.get("temporary_paths", [])
    if not isinstance(paths, list):
        return
    for path in paths:
        if isinstance(path, Path):
            shutil.rmtree(path, ignore_errors=True)


def _detect_vcs(actx: ArchContext) -> None:
    actx.vcs = is_git_repo(actx.root)


def _root_budget_skipped(ctx: Context, offset: int, root: Path) -> bool:
    expected = {
        "section": NAME,
        "reason": "budget",
        "details": str(root),
    }
    return expected in ctx.skipped[offset:]


def _checks_not_run(document: dict, checks: list) -> list[str]:
    timings = document.get("timings_s", {})
    return [
        check.KEY
        for check in sorted(checks, key=lambda item: (item.ORDER, item.KEY))
        if check.KEY not in timings
    ]


def collect(ctx: Context) -> dict:
    result = {}
    checks = discover_checks()
    for root in ctx.roots:
        root_deadline = time.monotonic() + ctx.flags.arch_root_seconds
        document = _document()
        actx = ArchContext(
            ctx=ctx,
            root=root,
            vcs=False,
            out=document,
            rule_inputs=document["rule_inputs"],
        )
        skipped_offset = len(ctx.skipped)
        try:
            _run_with_timeout(
                _detect_vcs,
                actx,
                root_deadline - time.monotonic(),
            )
            configured_seconds = ctx.flags.arch_root_seconds
            ctx.flags.arch_root_seconds = max(
                0.0, root_deadline - time.monotonic()
            )
            try:
                run_checks(actx, checks)
            finally:
                ctx.flags.arch_root_seconds = configured_seconds
            if (
                not _root_budget_skipped(ctx, skipped_offset, root)
                and time.monotonic() >= root_deadline
            ):
                ctx.skip(NAME, "budget", details=str(root))
                ctx.mark_truncated()
            if _root_budget_skipped(ctx, skipped_offset, root):
                document["checks_not_run"] = _checks_not_run(document, checks)
            result[str(root.resolve())] = document
        except _RootBudgetExpired:
            ctx.skip(NAME, "budget", details=str(root))
            ctx.mark_truncated()
            document["checks_not_run"] = _checks_not_run(document, checks)
            result[str(root.resolve())] = document
        except Exception as error:
            ctx.error(NAME, type(error).__name__)
            result[str(root.resolve())] = None
        finally:
            _cleanup(actx)
    return result
