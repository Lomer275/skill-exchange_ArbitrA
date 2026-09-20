import os
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
from envaudit.core.budget import allocate_root_budget
from envaudit.core.context import Context
from envaudit.core.runner import is_git_repo
from envaudit.core.walk import EXCLUDED_DIRS
from envaudit.core.worktrees import is_linked_worktree


NAME = "architecture"
ORDER = 80
ROOT_ESTIMATE_DEPTH = 2

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


def _estimate_root_files(root: Path) -> int:
    files = 0
    pending = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            files += 1
                            continue
                        if (
                            depth >= ROOT_ESTIMATE_DEPTH
                            or entry.name in EXCLUDED_DIRS
                            or not entry.is_dir(follow_symlinks=False)
                        ):
                            continue
                    except OSError:
                        continue
                    path = Path(entry.path)
                    if not is_linked_worktree(path):
                        pending.append((path, depth + 1))
        except OSError:
            continue
    return files


def _root_order(root: Path) -> tuple[int, str, str]:
    return (_estimate_root_files(root), root.name, str(root))


def _output_order(root: Path) -> tuple[str, str]:
    return (root.name, str(root))


def collect(ctx: Context) -> dict:
    result: dict[str, dict | None] = {}
    checks = discover_checks()
    root_count = len(ctx.roots)
    ordered_roots = sorted(ctx.roots, key=_root_order)
    for offset, root in enumerate(ordered_roots):
        roots_remaining = root_count - offset
        section_remaining = ctx.remaining_seconds()
        root_seconds = allocate_root_budget(
            section_remaining,
            roots_remaining,
            ctx.flags.arch_root_seconds,
        )
        root_deadline = time.monotonic() + root_seconds
        document = _document()
        if root_count > 1:
            document["root_budget_seconds"] = round(root_seconds, 6)
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
    return {
        str(root.resolve()): result[str(root.resolve())]
        for root in sorted(ctx.roots, key=_output_order)
    }
