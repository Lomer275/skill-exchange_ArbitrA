from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from .graph import Graph


def _imports(tree: ast.Module | None) -> set[str]:
    if tree is None:
        return set()
    output = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            output.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            output.add(node.module)
    return output


def analyse(graph: Graph, assignment: dict[str, str]) -> tuple[dict, dict]:
    non_http_callers: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        source_imports = _imports(graph.modules[edge.source].tree)
        if not any(name.startswith(("fastapi", "starlette")) for name in source_imports):
            non_http_callers[edge.target].add(edge.source)

    http_exception = []
    orm_in_interface = []
    application_framework = []
    for name, item in graph.modules.items():
        if not item.prod or item.tree is None:
            continue
        imported = _imports(item.tree)
        layer = assignment.get(item.path)
        if any(value.endswith("HTTPException") or value == "fastapi" for value in imported):
            http_exception.append(
                {
                    "path": item.path,
                    "non_http_callers": len(non_http_callers.get(name, set())),
                }
            )
        if layer == "interface":
            session_calls = sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"session", "db"}
                for node in ast.walk(item.tree)
            )
            if session_calls:
                orm_in_interface.append({"path": item.path, "calls": session_calls})
        if layer == "application" and any(value.startswith("django") for value in imported):
            application_framework.append(item.path)
    metrics = {
        "http_exception": http_exception,
        "orm_in_interface": orm_in_interface,
        "application_framework_imports": sorted(application_framework),
    }
    rule = {
        "http_exception_with_non_http_callers": sum(
            bool(item["non_http_callers"]) for item in http_exception
        ),
        "orm_in_interface": len(orm_in_interface),
        "application_framework_imports": len(application_framework),
    }
    return metrics, rule

