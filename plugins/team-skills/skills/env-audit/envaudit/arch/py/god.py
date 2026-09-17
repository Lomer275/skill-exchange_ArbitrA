from __future__ import annotations

from collections import deque
from pathlib import Path

from envaudit.arch import pyast
from envaudit.arch.context import ArchContext

from .graph import Graph, incoming


def _dispatcher_closure(actx: ArchContext, graph: Graph) -> set[str]:
    runtime = actx.out.get("runtime", {})
    anchors = runtime.get("anchors", []) if isinstance(runtime, dict) else []
    starts = [
        graph.by_path.get(anchor.get("entry", ""))
        for anchor in anchors
        if isinstance(anchor, dict)
    ]
    adjacency: dict[str, set[str]] = {name: set() for name in graph.modules}
    for edge in graph.edges:
        if not edge.type_checking:
            adjacency[edge.source].add(edge.target)
    seen = set()
    pending = deque(name for name in starts if name is not None)
    while pending:
        name = pending.popleft()
        if name in seen:
            continue
        seen.add(name)
        pending.extend(sorted(adjacency.get(name, set()) - seen))
    return seen


def _alt_growth(actx: ArchContext, graph: Graph, path: str) -> float | None:
    alt = actx.trees.get("alt")
    if alt is None:
        return None
    entry = next((item for item in actx.files("alt") if item.rel == path), None)
    current_name = graph.by_path.get(path)
    if entry is None or current_name is None:
        return None
    data = actx.read(entry)
    if data is None:
        return None
    alt_lines, _, _ = pyast.sloc(data, python=True)
    current = graph.modules[current_name].lines
    low, high = sorted((alt_lines, current))
    return round((high - low) / low, 6) if low else None


def analyse(
    actx: ArchContext,
    graph: Graph,
    direct_io: dict[str, set[str]],
    project_has_adapters: bool,
) -> tuple[list[dict], list[dict], dict]:
    prod_total = sum(item.sloc_no_strings for item in graph.modules.values() if item.prod)
    closure = _dispatcher_closure(actx, graph)
    churn = actx.churn() or {}
    frozen = set()
    classification = actx.out.get("classification")
    if isinstance(classification, dict):
        value = classification.get("frozen_zones", [])
        if isinstance(value, list):
            frozen = {str(item) for item in value}

    modules_top = []
    longest = []
    candidates = []
    signals = {}
    for name, item in graph.modules.items():
        if not item.prod:
            continue
        test_importers = len(incoming(graph, name, tests=True))
        is_models = Path(item.path).name == "models.py"
        composition = Path(item.path).name in {
            "settings.py",
            "wsgi.py",
            "asgi.py",
            "__main__.py",
            "manage.py",
        } or Path(item.path).name == "main.py"
        zone = Path(item.path).parts[0] if Path(item.path).parts else ""
        metric = {
            "path": item.path,
            "lines": item.lines,
            "sloc": item.sloc,
            "sloc_no_strings": item.sloc_no_strings,
            "top_defs": item.top_defs,
            "class_methods_max": item.class_methods_max,
            "longest_func": item.longest_func,
            "assign_share": item.assign_share,
            "share_of_prod": round(item.sloc_no_strings / prod_total, 6) if prod_total else 0.0,
            "churn": churn.get(item.path, (None, 0))[1] if churn else None,
            "direct_io_imports": sorted(direct_io.get(name, set())),
            "test_importers": test_importers,
            "is_composition_root": composition,
            "is_models_py": is_models,
            "frozen": zone in frozen,
            "in_dispatcher_closure": name in closure,
            "in_base": True,
        }
        modules_top.append(metric)
        if item.tree is not None:
            for node in item.tree.body:
                if not hasattr(node, "name") or not hasattr(node, "lineno"):
                    continue
                if node.__class__.__name__ not in {"FunctionDef", "AsyncFunctionDef"}:
                    continue
                lines = max(1, getattr(node, "end_lineno", node.lineno) - node.lineno + 1)
                longest.append({"path": item.path, "name": node.name, "lines": lines})

        qualifies = item.sloc_no_strings > 800 or item.top_defs + item.class_methods_max > 40
        excluded = (
            Path(item.path).name == "settings.py"
            or item.assign_share >= 0.8
            or is_models
            or item.data_shaped
        )
        if qualifies and not excluded:
            candidates.append(item.path)
            signals[item.path] = {
                "thin_module_claim": None,
                "growth_vs_alt": _alt_growth(actx, graph, item.path),
                "test_importers": test_importers,
                "in_dispatcher_closure": name in closure,
                "own_io_imports": sorted(direct_io.get(name, set())),
                "project_has_adapters": project_has_adapters,
            }

    modules_top.sort(key=lambda row: (-row["sloc_no_strings"], row["path"]))
    longest.sort(key=lambda row: (-row["lines"], row["path"], row["name"]))
    rule = {"candidates": sorted(candidates), "signals": signals}
    return modules_top[:30], longest[:5], rule
