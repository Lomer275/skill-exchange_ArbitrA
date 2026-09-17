from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

from envaudit.arch.context import ArchContext
from envaudit.core.runner import git, run
from envaudit.core.walk import EXCLUDED_DIRS

from .graph import Graph


COLLECTED = re.compile(rb"(?:^|\s)(\d+) tests? collected(?:\s|$)")
COLLECT_ERROR = re.compile(rb"(?:ERROR collecting|errors? during collection)", re.I)
MANUAL_GATE = re.compile(r"php\s+-l|pytest|ALL\s+PASS|прогнать\s+тесты", re.I)


def _test_file(path: str) -> bool:
    parts = tuple(part.casefold() for part in Path(path).parts)
    name = parts[-1] if parts else ""
    return (
        "tests" in parts[:-1]
        or "test" in parts[:-1]
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _copy_source(actx: ArchContext, target: Path) -> bool:
    view = actx.trees.get("primary")
    if view is None:
        return False
    if actx.vcs and view.sha:
        archived = git(actx.root, "archive", "--format=tar", view.sha, timeout=180)
        if archived.rc != 0:
            return False
        try:
            with tarfile.open(fileobj=BytesIO(archived.stdout), mode="r:") as bundle:
                for member in bundle.getmembers():
                    destination = Path(os.path.abspath(target / member.name))
                    if os.path.commonpath((str(destination), str(target))) != str(target):
                        return False
                bundle.extractall(target)
        except (tarfile.TarError, OSError, ValueError):
            return False
        return True

    excluded = set(EXCLUDED_DIRS) | {".git"}

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in excluded}

    try:
        shutil.copytree(view.path, target, dirs_exist_ok=True, ignore=ignore)
    except OSError:
        return False
    return True


def _collect(actx: ArchContext) -> tuple[int | None, int]:
    if not actx.ctx.flags.pytest_collect:
        actx.skip("python", "flag_off", "pytest_collect")
        return None, 0
    parent = Path(tempfile.mkdtemp(prefix="env-audit-"))
    project = parent / "project"
    project.mkdir()
    try:
        if not _copy_source(actx, project):
            actx.error("python", "pytest_copy_failed")
            return None, 1
        interpreter = actx.ctx.flags.pytest_python or "python3"
        command = [
            "/usr/bin/env",
            "-i",
            "PATH=/usr/bin:/bin",
            f"HOME={parent}",
            "PYTHONDONTWRITEBYTECODE=1",
            interpreter,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
        result = run(command, timeout=120, cwd=project)
        errors = len(COLLECT_ERROR.findall(result.stdout))
        if result.timed_out:
            actx.error("python", "pytest_collect_timeout")
            return None, max(errors, 1)
        if result.rc != 0:
            actx.error("python", "pytest_collect_failed")
            return None, max(errors, 1)
        matches = COLLECTED.findall(result.stdout)
        if errors or not matches:
            return None, max(errors, 1)
        return int(matches[-1]), 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def _manual_gate(actx: ArchContext) -> str | None:
    for entry in actx.files():
        path = entry.rel.casefold()
        if not path.startswith("docs/") or "deploy" not in path or Path(path).suffix != ".md":
            continue
        data = actx.read(entry)
        if data is not None and MANUAL_GATE.search(data.decode("utf-8", "replace")):
            return entry.rel
    return None


def analyse(actx: ArchContext, graph: Graph) -> dict:
    test_items = [item for item in graph.modules.values() if not item.prod]
    files = sum(_test_file(item.path) for item in test_items)
    lines = sum(item.lines for item in test_items if _test_file(item.path))
    collected, errors = _collect(actx)
    prod_components = {
        name.split(".", 1)[0]
        for name, item in graph.modules.items()
        if item.prod and name not in graph.package_nodes
    }
    tested_components = {
        edge.target.split(".", 1)[0]
        for edge in graph.edges
        if not graph.modules[edge.source].prod and graph.modules[edge.target].prod
    }
    gate = _manual_gate(actx)
    runtime = actx.out.get("runtime")
    if isinstance(runtime, dict):
        runtime["manual_gate_doc"] = gate
    output = {
        "files": files,
        "lines": lines,
        "collected": collected,
        "collect_errors": errors,
        "components_without_tests": sorted(prod_components - tested_components),
    }
    ci = runtime.get("ci", {}) if isinstance(runtime, dict) else {}
    live_units = actx.live_units() or []
    tree = actx.out.get("tree", {})
    output["rule"] = {
        "ci": bool(ci.get("files")) if isinstance(ci, dict) else False,
        "live_or_deploy": bool(live_units) or bool(ci.get("has_deploy_job")) if isinstance(ci, dict) else bool(live_units),
        "manual_gate": gate is not None,
        "repo_last_commit_at": tree.get("repo_last_commit_at") if isinstance(tree, dict) else None,
    }
    return output
