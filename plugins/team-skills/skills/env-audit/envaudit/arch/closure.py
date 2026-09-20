import ast
from collections import deque
import os
from pathlib import Path
import re

from envaudit.arch import pyast
from envaudit.arch.context import ArchContext, path_inside


_SHELL_ENTRY = re.compile(
    r"(?:^|[;&|]\s*)(?:python(?:\d+(?:\.\d+)?)?|bash)\s+"
    r"[\"']?([^\s\"';|&]+)",
    re.M,
)


def _module_name(rel: str, source_root: str) -> str | None:
    path = Path(rel)
    root = Path(source_root)
    try:
        local = path if source_root == "." else path.relative_to(root)
    except ValueError:
        return None
    parts = list(local.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or None


def _source_roots(actx: ArchContext) -> list[str]:
    tree = actx.out.get("tree", {})
    roots = ["."]
    if isinstance(tree, dict):
        for item in tree.get("source_roots", []):
            if not isinstance(item, dict) or item.get("language") != "python":
                continue
            value = item.get("path")
            if isinstance(value, str) and value not in roots:
                roots.append(value)
    return roots


def _module_map(actx: ArchContext, tree_id: str) -> dict[str, str]:
    result = {}
    roots = _source_roots(actx)
    for entry in actx.code_files(tree_id, exts=frozenset({".py"})):
        for root in roots:
            module = _module_name(entry.rel, root)
            if module:
                result.setdefault(module, entry.rel)
    return result


def _resolved_module(
    imported: str, current: str, modules: dict[str, str]
) -> str | None:
    if imported.startswith("."):
        level = len(imported) - len(imported.lstrip("."))
        suffix = imported[level:]
        package = current.split(".")[:-1]
        base = package[: max(0, len(package) - level + 1)]
        candidate = ".".join([*base, *([suffix] if suffix else [])])
    else:
        candidate = imported
    return modules.get(candidate)


def _python_targets(
    parsed: ast.Module,
    current: str,
    modules: dict[str, str],
) -> set[str]:
    targets = set()
    for imported, _, _ in pyast.imports(parsed):
        resolved = _resolved_module(imported, current, modules)
        if resolved:
            targets.add(resolved)
    for node in ast.walk(parsed):
        if not isinstance(node, ast.ImportFrom):
            continue
        prefix = "." * node.level + (node.module or "")
        for alias in node.names:
            if alias.name == "*":
                continue
            separator = "" if prefix.endswith(".") else "."
            candidate = f"{prefix}{separator}{alias.name}" if prefix else alias.name
            resolved = _resolved_module(candidate, current, modules)
            if resolved:
                targets.add(resolved)
    return targets


def _shell_targets(
    actx: ArchContext, tree_id: str, rel: str, data: bytes
) -> set[str]:
    view = actx.trees.get(tree_id)
    if view is None:
        return set()
    result = set()
    for match in _SHELL_ENTRY.finditer(data.decode("utf-8", "replace")):
        raw = match.group(1)
        candidate = Path(raw)
        if candidate.is_absolute():
            if not path_inside(candidate, actx.root):
                continue
            try:
                candidate = candidate.relative_to(actx.root)
            except ValueError:
                continue
        else:
            candidate = Path(rel).parent / candidate
        normalized = Path(os.path.normpath(candidate)).as_posix()
        if normalized.startswith("../"):
            continue
        target = view.path / normalized
        if target.is_file() and path_inside(Path(os.path.abspath(target)), view.path):
            result.add(normalized)
    return result


def import_closure(
    actx: ArchContext, entry_rel: str, tree_id: str = "primary"
) -> set[str]:
    """Return the local Python/shell closure rooted at ``entry_rel``."""
    entries = {entry.rel: entry for entry in actx.files(tree_id)}
    if entry_rel not in entries:
        return set()
    modules = _module_map(actx, tree_id)
    rel_modules = {rel: module for module, rel in modules.items()}
    seen = set()
    pending = deque([entry_rel])
    while pending:
        rel = pending.popleft()
        if rel in seen:
            continue
        entry = entries.get(rel)
        if entry is None:
            continue
        seen.add(rel)
        data = actx.read(entry)
        if data is None:
            continue
        suffix = Path(rel).suffix.lower()
        targets = set()
        if suffix == ".py":
            parsed = pyast.parse(data, rel)
            current = rel_modules.get(rel)
            if parsed is not None and current is not None:
                targets = _python_targets(parsed, current, modules)
        elif suffix == ".sh":
            targets = _shell_targets(actx, tree_id, rel, data)
        pending.extend(sorted(targets - seen))
    return seen
