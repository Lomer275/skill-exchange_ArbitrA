from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from envaudit.arch import pyast
from envaudit.arch.context import ArchContext


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    line: int
    level: str
    type_checking: bool
    in_ready: bool
    annotation_only: bool


@dataclass
class Module:
    name: str
    path: str
    tree: ast.Module | None
    data: bytes
    prod: bool
    package: bool
    lines: int
    sloc: int
    sloc_no_strings: int
    top_defs: int = 0
    class_methods_max: int = 0
    longest_func: int = 0
    assign_share: float = 0.0
    data_shaped: bool = False
    imports: set[str] = field(default_factory=set)


@dataclass
class Graph:
    modules: dict[str, Module]
    by_path: dict[str, str]
    edges: list[Edge]
    package_nodes: set[str]

    @property
    def prod_modules(self) -> set[str]:
        return {name for name, item in self.modules.items() if item.prod}


def module_name(rel: str) -> str:
    path = Path(rel)
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _prod_path(actx: ArchContext, rel: str) -> bool:
    if actx.is_prod_path(rel):
        return True
    parts = tuple(part.casefold() for part in Path(rel).parts)
    if not parts or parts[-1] == "conftest.py":
        return False
    excluded = {"tests", "test", "migrations", ".venv", "venv", "node_modules", "build", "dist"}
    return not any(part in excluded for part in parts[:-1])


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _span(node: ast.AST) -> int:
    return max(1, getattr(node, "end_lineno", node.lineno) - node.lineno + 1)


def _module_stats(item: Module) -> None:
    tree = item.tree
    if tree is None:
        return
    definitions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    item.top_defs = len(definitions)
    item.class_methods_max = max(
        (
            sum(
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                for child in node.body
            )
            for node in definitions
            if isinstance(node, ast.ClassDef)
        ),
        default=0,
    )
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    item.longest_func = max((_span(node) for node in functions), default=0)
    assignments = sum(
        _span(node)
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    )
    item.assign_share = round(assignments / max(item.sloc_no_strings, 1), 6)
    literal_lines = set()
    for node in ast.walk(tree):
        value = None
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
        elif isinstance(node, ast.Expr):
            value = node.value
        if isinstance(value, (ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Dict)):
            literal_lines.update(
                range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1)
            )
    item.data_shaped = len(literal_lines) / max(item.sloc, 1) >= 0.8


class _UsageVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.annotation_depth = 0
        self.annotation_names: set[str] = set()
        self.runtime_names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        target = self.annotation_names if self.annotation_depth else self.runtime_names
        target.add(node.id)

    def _annotation(self, node: ast.AST | None) -> None:
        if node is None:
            return
        self.annotation_depth += 1
        self.visit(node)
        self.annotation_depth -= 1

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for argument in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            self._annotation(argument.annotation)
        self._annotation(node.args.vararg.annotation if node.args.vararg else None)
        self._annotation(node.args.kwarg.annotation if node.args.kwarg else None)
        self._annotation(node.returns)
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)
        for child in node.body:
            self.visit(child)

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.visit(node.target)
        self._annotation(node.annotation)
        if node.value is not None:
            self.visit(node.value)

    def visit_Import(self, node: ast.Import) -> None:
        return

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        return


class _EdgeVisitor(ast.NodeVisitor):
    def __init__(self, source: str, modules: set[str], tree: ast.Module) -> None:
        self.source = source
        self.modules = modules
        self.result: list[tuple[str, int, str, bool, bool, bool]] = []
        self.function_depth = 0
        self.type_depth = 0
        self.ready_depth = 0
        self.annotation_depth = 0
        usage = _UsageVisitor()
        usage.visit(tree)
        self.annotation_names = usage.annotation_names
        self.runtime_names = usage.runtime_names

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.function_depth += 1
        if node.name == "ready":
            self.ready_depth += 1
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)
        for argument in [
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ]:
            if argument.annotation is not None:
                self.annotation_depth += 1
                self.visit(argument.annotation)
                self.annotation_depth -= 1
        if node.returns is not None:
            self.annotation_depth += 1
            self.visit(node.returns)
            self.annotation_depth -= 1
        for child in node.body:
            self.visit(child)
        if node.name == "ready":
            self.ready_depth -= 1
        self.function_depth -= 1

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_If(self, node: ast.If) -> None:
        marker = _call_name(node.test)
        guarded = marker in {"TYPE_CHECKING", "typing.TYPE_CHECKING"}
        self.visit(node.test)
        if guarded:
            self.type_depth += 1
        for child in node.body:
            self.visit(child)
        if guarded:
            self.type_depth -= 1
        for child in node.orelse:
            self.visit(child)

    def _append(self, imported: str, line: int, binding: str) -> None:
        self.result.append(
            (
                imported,
                line,
                "lazy" if self.function_depth else "module",
                bool(self.type_depth),
                bool(self.ready_depth),
                binding in self.annotation_names and binding not in self.runtime_names,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._append(alias.name, node.lineno, alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        prefix = "." * node.level + (node.module or "")
        resolved_parent = _resolve(self.source, prefix, self.modules)
        for alias in node.names:
            separator = "" if prefix.endswith(".") else "."
            child = f"{prefix}{separator}{alias.name}" if prefix else alias.name
            resolved_child = _resolve(self.source, child, self.modules)
            self._append(
                child if resolved_child is not None else prefix,
                node.lineno,
                alias.asname or alias.name,
            )


def _resolve(source: str, imported: str, modules: set[str]) -> str | None:
    if not imported:
        return None
    if imported.startswith("."):
        level = len(imported) - len(imported.lstrip("."))
        suffix = imported[level:].lstrip(".")
        package = source.split(".")[:-1]
        base = package[: max(0, len(package) - level + 1)]
        candidate = ".".join([*base, *([suffix] if suffix else [])])
    else:
        candidate = imported
    parts = candidate.split(".")
    for length in range(len(parts), 0, -1):
        value = ".".join(parts[:length])
        if value in modules:
            return value
    return None


def _reexports(modules: dict[str, Module]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    names = set(modules)
    for name, item in modules.items():
        if not item.package or item.tree is None:
            continue
        for node in item.tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            prefix = "." * node.level + (node.module or "")
            parent = _resolve(name + ".__init__", prefix, names)
            for alias in node.names:
                separator = "" if prefix.endswith(".") else "."
                child = _resolve(
                    name + ".__init__",
                    f"{prefix}{separator}{alias.name}" if prefix else alias.name,
                    names,
                )
                target = child or parent
                if target is not None and target != name:
                    result[name].add(target)
    return result


def build(actx: ArchContext) -> Graph:
    cached = actx.cache.get("python_graph")
    if isinstance(cached, Graph):
        return cached
    modules: dict[str, Module] = {}
    by_path: dict[str, str] = {}
    for entry in actx.code_files(exts=frozenset({".py"})):
        name = module_name(entry.rel)
        if not name:
            continue
        data = actx.read(entry)
        if data is None:
            continue
        parsed = pyast.parse(data, entry.rel)
        lines, logical, no_strings = pyast.sloc(data, python=True)
        item = Module(
            name=name,
            path=entry.rel,
            tree=parsed,
            data=data,
            prod=_prod_path(actx, entry.rel),
            package=Path(entry.rel).name == "__init__.py",
            lines=lines,
            sloc=logical,
            sloc_no_strings=no_strings,
        )
        _module_stats(item)
        modules[name] = item
        by_path[entry.rel] = name

    names = set(modules)
    raw_edges: list[Edge] = []
    for name, item in modules.items():
        if item.tree is None:
            continue
        visitor = _EdgeVisitor(name, names, item.tree)
        visitor.visit(item.tree)
        for imported, line, level, type_checking, in_ready, annotation_only in visitor.result:
            target = _resolve(name, imported, names)
            if target is None or target == name:
                continue
            item.imports.add(target)
            raw_edges.append(
                Edge(
                    name,
                    target,
                    line,
                    level,
                    type_checking,
                    in_ready,
                    annotation_only,
                )
            )

    redirects = _reexports(modules)
    edges = []
    seen = set()
    for edge in raw_edges:
        targets = redirects.get(edge.target) or {edge.target}
        for target in targets:
            key = (
                edge.source,
                target,
                edge.line,
                edge.level,
                edge.type_checking,
                edge.in_ready,
                edge.annotation_only,
            )
            if key in seen or target == edge.source:
                continue
            seen.add(key)
            edges.append(
                Edge(
                    edge.source,
                    target,
                    edge.line,
                    edge.level,
                    edge.type_checking,
                    edge.in_ready,
                    edge.annotation_only,
                )
            )
    result = Graph(
        modules=modules,
        by_path=by_path,
        edges=sorted(
            edges,
            key=lambda edge: (edge.source, edge.target, edge.line, edge.level),
        ),
        package_nodes={name for name, item in modules.items() if item.package},
    )
    actx.cache["python_graph"] = result
    return result


def _adjacency(nodes: Iterable[str], edges: Iterable[tuple[str, str]]) -> dict[str, set[str]]:
    result = {node: set() for node in nodes}
    for source, target in edges:
        if source != target and source in result and target in result:
            result[source].add(target)
    return result


def iterative_tarjan(adjacency: dict[str, set[str]]) -> list[list[str]]:
    """Return non-trivial SCCs without using the Python call stack."""
    index = 0
    indexes: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    for root in sorted(adjacency):
        if root in indexes:
            continue
        frames: list[tuple[str, object, str | None, bool]] = [
            (root, iter(sorted(adjacency[root])), None, False)
        ]
        while frames:
            node, children, parent, entered = frames[-1]
            if not entered:
                indexes[node] = low[node] = index
                index += 1
                stack.append(node)
                on_stack.add(node)
                frames[-1] = (node, children, parent, True)
            try:
                child = next(children)  # type: ignore[arg-type]
            except StopIteration:
                frames.pop()
                if parent is not None:
                    low[parent] = min(low[parent], low[node])
                if low[node] == indexes[node]:
                    component = []
                    while stack:
                        member = stack.pop()
                        on_stack.remove(member)
                        component.append(member)
                        if member == node:
                            break
                    if len(component) >= 2:
                        components.append(sorted(component))
                continue
            if child not in indexes:
                frames.append((child, iter(sorted(adjacency[child])), node, False))
            elif child in on_stack:
                low[node] = min(low[node], indexes[child])
    return sorted(components, key=lambda item: (-len(item), item))


def _package(name: str, depth: int, package_nodes: set[str]) -> str:
    parts = name.split(".")
    if len(parts) == 1 and name not in package_nodes:
        return "."
    return ".".join(parts[: min(depth, len(parts))])


def _component_record(
    component: list[str], graph: Graph, selected: list[Edge]
) -> dict:
    members = set(component)

    def comment_above(edge: Edge) -> bool:
        lines = graph.modules[edge.source].data.decode("utf-8", "replace").splitlines()
        return edge.line > 1 and edge.line - 2 < len(lines) and lines[edge.line - 2].lstrip().startswith("#")

    lazy = [
        {
            "source": graph.modules[edge.source].path,
            "target": graph.modules[edge.target].path,
            "line": edge.line,
            "comment_above": comment_above(edge),
        }
        for edge in selected
        if edge.level == "lazy"
        and edge.source in members
        and edge.target in members
    ]
    return {
        "size": len(component),
        "members": [graph.modules[name].path for name in component[:20]],
        "crosses_packages": len({_package(name, 1, graph.package_nodes) for name in component}) > 1,
        "lazy_edges": lazy[:20],
        "name_in_tests": any(
            edge.target in members and not graph.modules[edge.source].prod
            for edge in graph.edges
        ),
    }


def cycles(graph: Graph) -> dict:
    prod = graph.prod_modules
    eligible = [
        edge
        for edge in graph.edges
        if edge.source in prod
        and edge.target in prod
        and not edge.type_checking
        and not (
            edge.source in graph.package_nodes
            and edge.target.startswith(edge.source + ".")
        )
    ]
    module_edges = [edge for edge in eligible if edge.level == "module"]
    combined = eligible

    def records(selected: list[Edge]) -> list[dict]:
        adjacency = _adjacency(prod, ((edge.source, edge.target) for edge in selected))
        return [
            _component_record(component, graph, selected)
            for component in iterative_tarjan(adjacency)
        ]

    def package_records(depth: int) -> list[dict]:
        nodes = {_package(name, depth, graph.package_nodes) for name in prod}
        pairs = {
            (
                _package(edge.source, depth, graph.package_nodes),
                _package(edge.target, depth, graph.package_nodes),
            )
            for edge in module_edges
            if _package(edge.source, depth, graph.package_nodes)
            != _package(edge.target, depth, graph.package_nodes)
        }
        output = []
        for component in iterative_tarjan(_adjacency(nodes, pairs)):
            output.append(
                {
                    "size": len(component),
                    "members": component[:20],
                    "crosses_packages": len(component) > 1,
                    "lazy_edges": [],
                    "name_in_tests": False,
                }
            )
        return output

    return {
        "module_level": records(module_edges),
        "with_lazy": records(combined),
        "top_packages": package_records(1),
        "second_packages": package_records(2),
    }


def incoming(graph: Graph, name: str, *, tests: bool | None = None) -> set[str]:
    result = set()
    for edge in graph.edges:
        if edge.target != name or edge.type_checking:
            continue
        source = graph.modules[edge.source]
        if tests is not None and source.prod == tests:
            continue
        if edge.source in graph.package_nodes:
            continue
        result.add(edge.source)
    return result


def fan_in(actx: ArchContext, rel_path: str) -> int:
    graph = build(actx)
    name = graph.by_path.get(rel_path)
    if name is None or name in graph.package_nodes:
        return 0
    return len(
        {
            edge.source
            for edge in graph.edges
            if edge.target == name
            and graph.modules[edge.source].prod
            and not edge.type_checking
            and edge.source not in graph.package_nodes
        }
    )


def edge_counts(graph: Graph) -> dict:
    prod_edges = [
        edge
        for edge in graph.edges
        if graph.modules[edge.source].prod and graph.modules[edge.target].prod
    ]
    return {
        "total": len(graph.edges),
        "prod": len(prod_edges),
        "module": sum(edge.level == "module" for edge in prod_edges),
        "lazy": sum(edge.level == "lazy" for edge in prod_edges),
        "type_checking": sum(edge.type_checking for edge in prod_edges),
        "in_ready": sum(edge.in_ready for edge in prod_edges),
        "annotation_only": sum(edge.annotation_only for edge in prod_edges),
        "prod_to_tests": sum(
            graph.modules[edge.source].prod and not graph.modules[edge.target].prod
            for edge in graph.edges
        ),
    }


def package_edges(graph: Graph) -> list[dict]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for edge in graph.edges:
        if not graph.modules[edge.source].prod or not graph.modules[edge.target].prod:
            continue
        source = _package(edge.source, 1, graph.package_nodes)
        target = _package(edge.target, 1, graph.package_nodes)
        if source != target:
            counts[(source, target)] += 1
    return [
        {"source": source, "target": target, "edges": count}
        for (source, target), count in sorted(counts.items())
    ]
