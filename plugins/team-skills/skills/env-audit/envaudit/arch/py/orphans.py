from __future__ import annotations

import ast
from pathlib import Path
import re

from envaudit.arch import pyast
from envaudit.arch.context import ArchContext
from envaudit.core.runner import git

from .graph import Graph, incoming


REFERENCE_FILES = re.compile(
    r"(?:^|/)(?:settings[^/]*\.py|urls\.py|pytest\.ini|setup\.cfg|pyproject\.toml|gunicorn[^/]*\.py)$"
    r"|(?:^|/)(?:docker-)?compose[^/]*\.(?:yml|yaml)$"
    r"|(?:^|/)(?:deploy/.*\.(?:service|timer)|\.github/workflows/.*\.(?:yml|yaml))$",
    re.I,
)
AGENT_FILES = re.compile(r"(?:^|/)(?:CLAUDE|AGENTS)\.md$", re.I)


def _anchors(actx: ArchContext) -> set[str]:
    runtime = actx.out.get("runtime", {})
    values = runtime.get("anchors", []) if isinstance(runtime, dict) else []
    return {
        item["entry"]
        for item in values
        if isinstance(item, dict) and isinstance(item.get("entry"), str)
    }


def _reference_text(actx: ArchContext) -> str:
    values = []
    for entry in actx.files():
        if not REFERENCE_FILES.search(entry.rel):
            continue
        data = actx.read(entry)
        if data is not None:
            values.append(data.decode("utf-8", "replace"))
    return "\n".join(values)


def _mentioned(text: str, dotted: str, basename: str) -> bool:
    patterns = (dotted, dotted.rsplit(".", 1)[0], basename)
    return any(
        value and re.search(rf"(?<![\w.]){re.escape(value)}(?![\w.])", text)
        for value in patterns
    )


def _dynamic_targets(graph: Graph) -> set[str]:
    output = set()
    loaders = {"import_module", "__import__", "run_module", "run_path", "spec_from_file_location"}
    for item in graph.modules.values():
        if item.tree is None:
            continue
        for node in ast.walk(item.tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            else:
                name = None
            if name not in loaders:
                continue
            output.update(
                argument.value
                for argument in node.args
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
            )
    return output


def _loaded_template_tags(actx: ArchContext) -> set[str]:
    output = set()
    marker = re.compile(r"{%\s*load\s+([^%}]+)")
    for entry in actx.files():
        if Path(entry.rel).suffix.lower() not in {".html", ".jinja", ".jinja2", ".txt"}:
            continue
        data = actx.read(entry)
        if data is None:
            continue
        for match in marker.finditer(data.decode("utf-8", "replace")):
            output.update(match.group(1).split())
    return output


def _django_apps(graph: Graph) -> set[str]:
    output = set()
    for item in graph.modules.values():
        if not Path(item.path).name.startswith("settings") or item.tree is None:
            continue
        for node in item.tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(isinstance(target, ast.Name) and target.id == "INSTALLED_APPS" for target in targets):
                continue
            value = node.value
            if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                continue
            for element in value.elts:
                if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                    continue
                app = element.value.split(".apps.", 1)[0]
                output.add(app)
    return output


def _django_discovered(path: str, loaded_tags: set[str], apps: set[str]) -> bool:
    item = Path(path)
    name = item.name
    package = ".".join(item.with_suffix("").parts[:-1])
    installed = any(
        package == app
        or package.endswith("." + app)
        or package.startswith(app + ".")
        for app in apps
    )
    if not installed:
        return False
    if name in {"admin.py", "apps.py", "signals.py", "checks.py"}:
        return True
    parts = item.parts
    if "templatetags" not in parts or name == "__init__.py":
        return False
    return item.stem in loaded_tags


def _documented(actx: ArchContext, path: str) -> list[str]:
    output = []
    marker = re.compile(r"`" + re.escape(path) + r"`")
    inactive = re.compile(r"удал[её]н|legacy|deprecated", re.I)
    for entry in actx.files():
        if not AGENT_FILES.search(entry.rel):
            continue
        data = actx.read(entry)
        if data is None:
            continue
        for line in data.decode("utf-8", "replace").splitlines():
            if marker.search(line) and not inactive.search(line):
                output.append(entry.rel)
                break
    return sorted(output)


def _branches(actx: ArchContext) -> list[str]:
    tree = actx.out.get("tree", {})
    if not isinstance(tree, dict):
        return []
    head = tree.get("head")
    candidates = []
    for item in [*tree.get("local_branches", []), *tree.get("worktrees", [])]:
        if not isinstance(item, dict) or item.get("local_only") is not True:
            continue
        sha = item.get("head")
        if isinstance(sha, str) and sha != head and sha not in candidates:
            candidates.append(sha)
    return candidates


def _tracked_paths(actx: ArchContext) -> set[str] | None:
    if not actx.vcs:
        return None
    view = actx.trees.get("primary")
    if view is not None and view.sha:
        result = git(actx.root, "ls-tree", "-r", "--name-only", "-z", view.sha)
    else:
        result = git(actx.root, "ls-files", "-z")
    if result.rc != 0:
        return None
    return {
        value.decode("utf-8", "surrogateescape")
        for value in result.stdout.split(b"\x00")
        if value
    }


def _used_on_branch(actx: ArchContext, path: str, refs: list[str]) -> tuple[bool, int]:
    dotted = path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
    basename = Path(path).stem
    checked = 0
    for sha in refs:
        if actx.ctx.expired():
            break
        result = git(
            actx.root,
            "grep",
            "-l",
            "-F",
            "-w",
            "-e",
            dotted,
            "-e",
            basename,
            sha,
            "--",
            timeout=30,
        )
        checked += 1
        if result.rc == 0:
            paths = result.stdout.decode("utf-8", "surrogateescape").splitlines()
            if any(not value.endswith(":" + path) and value != path for value in paths):
                return True, checked
    return False, checked


def analyse(actx: ArchContext, graph: Graph) -> tuple[list[dict], dict[str, dict]]:
    anchors = _anchors(actx)
    refs = _branches(actx)
    reference_text = _reference_text(actx)
    dynamic_targets = _dynamic_targets(graph)
    loaded_tags = _loaded_template_tags(actx)
    django_apps = _django_apps(graph)
    tracked = _tracked_paths(actx)
    output = []
    by_path = {}
    branches_checked = 0
    for name, item in sorted(graph.modules.items(), key=lambda pair: pair[1].path):
        if not item.prod or item.package:
            continue
        if tracked is not None and item.path not in tracked:
            continue
        if incoming(graph, name, tests=False):
            continue
        path = item.path
        path_parts = Path(path).parts
        if (
            path in anchors
            or Path(path).name == "__main__.py"
            or item.tree is not None and pyast.has_main_guard(item.tree)
            or "management" in path_parts and "commands" in path_parts
            or _django_discovered(path, loaded_tags, django_apps)
        ):
            continue
        dotted = name
        basename = Path(path).name
        if _mentioned(reference_text, dotted, basename):
            continue
        if dynamic_targets & {dotted, basename, basename.removesuffix(".py")}:
            continue
        used, checked = _used_on_branch(actx, path, refs)
        branches_checked = max(branches_checked, checked)
        if used:
            continue
        docs = _documented(actx, path)
        kind = "test_only" if incoming(graph, name, tests=True) else "orphan"
        record = {
            "path": path,
            "lines": item.lines,
            "class": kind,
            "documented_as_active_in": docs,
            "branches_checked": checked,
            "branches_total": len(refs),
        }
        output.append(record)
        by_path[path] = record
    actx.cache["python_orphan_branch_stats"] = {
        "checked": branches_checked,
        "total": len(refs),
    }
    return output, by_path
