from __future__ import annotations

import ast
from collections import deque
import json
from pathlib import Path
import re

from envaudit.arch import pyast
from envaudit.arch.context import ArchContext

from .graph import Graph


DIST_ALIASES = {
    "pyjwt": "jwt",
    "python-dotenv": "dotenv",
    "pymupdf": "fitz",
    "pillow": "PIL",
    "beautifulsoup4": "bs4",
    "scikit-learn": "sklearn",
    "pyyaml": "yaml",
    "python-telegram-bot": "telegram",
}
THIRD_PARTY_IO = {
    "aiohttp",
    "requests",
    "httpx",
    "redis",
    "openai",
    "anthropic",
    "supabase",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "sqlalchemy",
    "aiogram",
    "maxapi",
    "umaxbot",
    "telegram",
    "boto3",
}
STDLIB_IO = {
    "sqlite3",
    "urllib",
    "http.client",
    "http.server",
    "socket",
    "ssl",
    "subprocess",
    "fcntl",
    "smtplib",
    "ftplib",
}
IO_BUILTINS = {"open", "input", "print"}
LAYERS = {"core", "application", "adapters", "interface", "composition", "tools"}


def _text(actx: ArchContext, rel: str) -> str | None:
    entry = next((item for item in actx.files() if item.rel == rel), None)
    if entry is None:
        return None
    data = actx.read(entry)
    return data.decode("utf-8", "replace") if data is not None else None


def _manifest_names(actx: ArchContext) -> tuple[list[str], set[str]]:
    manifests = []
    distributions = set()
    requirement = re.compile(r"^\s*([A-Za-z0-9_.-]+)")
    quoted = re.compile(r"['\"]([A-Za-z0-9_.-]+)(?:\[[^]]+\])?(?:[<>=!~].*)?['\"]")
    for entry in actx.files():
        name = Path(entry.rel).name
        if not (
            (name.startswith("requirements") and name.endswith(".txt"))
            or name in {"pyproject.toml", "setup.py"}
        ):
            continue
        data = actx.read(entry)
        if data is None:
            continue
        manifests.append(entry.rel)
        text = data.decode("utf-8", "replace")
        if name.startswith("requirements"):
            for line in text.splitlines():
                clean = line.split("#", 1)[0]
                match = requirement.match(clean)
                if match:
                    distributions.add(match.group(1))
        else:
            distributions.update(quoted.findall(text))
    imports = {
        DIST_ALIASES.get(name.casefold(), name.replace("-", "_").split("[", 1)[0])
        for name in distributions
        if name
    }
    return sorted(manifests), imports


def _direct_imports(tree: ast.Module | None) -> set[str]:
    if tree is None:
        return set()
    result = set()
    for name, _, _ in pyast.imports(tree):
        if not name or name.startswith("."):
            continue
        result.add(name.split(".", 1)[0])
    return result


def io_imports(tree: ast.Module | None) -> set[str]:
    imported = _direct_imports(tree)
    output = imported & THIRD_PARTY_IO
    for name in STDLIB_IO:
        top = name.split(".", 1)[0]
        if name in imported or top in imported:
            output.add(name)
    return output


def _composition(path: str) -> bool:
    name = Path(path).name
    return (
        name in {"settings.py", "wsgi.py", "asgi.py", "__main__.py", "apps.py", "manage.py"}
        or (name == "main.py" and len(Path(path).parts) > 1)
    )


def _decorated_interface(tree: ast.Module | None) -> bool:
    if tree is None:
        return False
    dispatcher_objects = set()
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        name = _call_name(value.func)
        if name and name.rsplit(".", 1)[-1] in {"Dispatcher", "Router"}:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            dispatcher_objects.update(
                target.id for target in targets if isinstance(target, ast.Name)
            )
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                name = _call_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
                if not name:
                    continue
                owner = name.split(".", 1)[0]
                if owner in dispatcher_objects or name.startswith(("router.", "app.")):
                    return True
        if isinstance(node, ast.ClassDef) and any(
            isinstance(base, ast.Name) and base.id in {"View", "BaseCommand"}
            for base in node.bases
        ):
            return True
    calls = {
        _call_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    return bool({"add_route", "do_GET", "do_POST"} & {name.rsplit(".", 1)[-1] for name in calls if name})


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _declared_assignments(actx: ArchContext, graph: Graph) -> dict[str, str]:
    text = _text(actx, ".audit/layers.json")
    if text is None:
        return {}
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return {}
    output = {}
    if not isinstance(document, dict):
        return output
    for layer, values in document.items():
        if layer not in LAYERS or not isinstance(values, (str, list)):
            continue
        prefixes = [values] if isinstance(values, str) else values
        for name, item in graph.modules.items():
            if any(
                isinstance(prefix, str)
                and (item.path == prefix or item.path.startswith(prefix.rstrip("/") + "/"))
                for prefix in prefixes
            ):
                output[name] = layer
    return output


def _flat(graph: Graph) -> bool:
    prod = [item for item in graph.modules.values() if item.prod]
    return bool(prod) and all(len(Path(item.path).parts) == 1 for item in prod)


def _channel_interfaces(actx: ArchContext, graph: Graph) -> set[str]:
    runtime = actx.out.get("runtime", {})
    anchors = runtime.get("anchors", []) if isinstance(runtime, dict) else []
    adjacency = {name: set() for name in graph.modules}
    for edge in graph.edges:
        if not edge.type_checking:
            adjacency[edge.source].add(edge.target)
    output = set()
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        entry = anchor.get("entry")
        name = graph.by_path.get(entry) if isinstance(entry, str) else None
        if name is None:
            continue
        imported = _direct_imports(graph.modules[name].tree)
        if not imported & {"aiogram", "maxapi", "umaxbot", "telegram"}:
            continue
        package = name.split(".", 1)[0]
        pending = deque([name])
        while pending:
            current = pending.popleft()
            if current in output or not (current == package or current.startswith(package + ".")):
                continue
            output.add(current)
            pending.extend(sorted(adjacency[current] - output))
    return output


def _fn_layers(graph: Graph) -> dict | None:
    if not _flat(graph):
        return None
    functions = []
    for item in graph.modules.values():
        if not item.prod or item.tree is None:
            continue
        for node in item.tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = {
                _call_name(child.func)
                for child in ast.walk(node)
                if isinstance(child, ast.Call)
            }
            external = bool(
                IO_BUILTINS & {name for name in calls if name}
                or any(
                    name and name.split(".", 1)[0] in THIRD_PARTY_IO
                    for name in calls
                )
            )
            functions.append(
                {
                    "path": item.path,
                    "name": node.name,
                    "layer": "adapters" if external else "core",
                }
            )
    return {"heuristic": True, "functions": functions[:200]}


def analyse(actx: ArchContext, graph: Graph) -> dict:
    manifests, framework_names = _manifest_names(actx)
    direct = {name: _direct_imports(item.tree) for name, item in graph.modules.items()}
    direct_io = {name: io_imports(item.tree) for name, item in graph.modules.items()}
    assignment = _declared_assignments(actx, graph)
    declared = bool(assignment)
    channel_interfaces = _channel_interfaces(actx, graph)

    remaining = {
        name for name, item in graph.modules.items() if item.prod and name not in assignment
    }
    for name in sorted(tuple(remaining)):
        if _composition(graph.modules[name].path):
            assignment[name] = "composition"
            remaining.remove(name)
    for name in sorted(tuple(remaining)):
        if name in channel_interfaces or _decorated_interface(graph.modules[name].tree):
            assignment[name] = "interface"
            remaining.remove(name)
    for name in sorted(tuple(remaining)):
        if direct_io[name]:
            assignment[name] = "adapters"
            remaining.remove(name)

    candidates = set(remaining)
    for name in tuple(candidates):
        imported = direct[name]
        if imported & framework_names or imported & THIRD_PARTY_IO:
            candidates.remove(name)
            continue
        if any(
            value in STDLIB_IO or value.split(".", 1)[0] in {item.split(".", 1)[0] for item in STDLIB_IO}
            for value in imported
        ):
            candidates.remove(name)
    changed = True
    edge_targets = {
        name: {
            edge.target
            for edge in graph.edges
            if edge.source == name and edge.level == "module" and not edge.type_checking
        }
        for name in candidates
    }
    while changed:
        changed = False
        for name in tuple(candidates):
            if edge_targets[name] - candidates:
                candidates.remove(name)
                changed = True
    for name in candidates:
        assignment[name] = "core"
        remaining.discard(name)
    for name in remaining:
        assignment[name] = "application"

    layer_edges = []
    for edge in graph.edges:
        if edge.level != "module" or edge.type_checking:
            continue
        source_layer = assignment.get(edge.source)
        target_layer = assignment.get(edge.target)
        if source_layer is None or target_layer is None or source_layer == target_layer:
            continue
        layer_edges.append(
            {
                "source": graph.modules[edge.source].path,
                "target": graph.modules[edge.target].path,
                "source_layer": source_layer,
                "target_layer": target_layer,
            }
        )

    core_io = []
    for name, layer in sorted(assignment.items()):
        if layer != "core":
            continue
        imports = sorted(direct_io[name])
        function_calls = []
        tree = graph.modules[name].tree
        if tree is not None:
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                calls = sorted(
                    {
                        called
                        for child in ast.walk(node)
                        if isinstance(child, ast.Call)
                        for called in [_call_name(child.func)]
                        if called and (
                            called in IO_BUILTINS
                            or called.split(".", 1)[0] in THIRD_PARTY_IO
                            or called.split(".", 1)[0] in {item.split(".", 1)[0] for item in STDLIB_IO}
                        )
                    }
                )
                if calls:
                    function_calls.append({"function": node.name, "calls": calls})
        if imports or function_calls:
            core_io.append(
                {
                    "path": graph.modules[name].path,
                    "imports": imports,
                    "functions": function_calls,
                }
            )

    output = {
        "fn_layers": _fn_layers(graph),
        "layers": {
            "source": "audit_json" if declared else "computed",
            "assignment": {
                graph.modules[name].path: layer
                for name, layer in sorted(assignment.items())
            },
            "unclassified": sorted(
                item.path
                for name, item in graph.modules.items()
                if item.prod and name not in assignment
            ),
        },
        "layer_edges": layer_edges,
        "framework_libs": {
            "source_manifests": manifests,
            "names": sorted(framework_names),
            "io_list_source": "manifest+builtin",
            "io_list_size": len(THIRD_PARTY_IO | STDLIB_IO),
        },
        "core_io": core_io,
        "direct_io": direct_io,
        "project_has_adapters": any(layer == "adapters" for layer in assignment.values()),
    }
    actx.cache["python_layers"] = output
    return output
