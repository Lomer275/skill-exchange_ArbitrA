from __future__ import annotations

import ast
from collections import defaultdict, deque
from difflib import SequenceMatcher
from pathlib import Path

from envaudit.arch.context import ArchContext
from envaudit.core.dockerignore import load_matcher
from envaudit.core.runner import git

from .graph import Graph


SDK_NAMES = {"aiogram", "maxapi", "umaxbot", "telegram"}


def _anchor_id(anchor: dict) -> str:
    location = anchor.get("file") or anchor.get("entry") or "live"
    line = anchor.get("line")
    return f"{anchor.get('kind')}:{location}" + (f":{line}" if line else "")


def _sdk_imports(item) -> set[str]:
    if item is None or item.tree is None:
        return set()
    output = set()
    for node in ast.walk(item.tree):
        if isinstance(node, ast.Import):
            output.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            output.add(node.module.split(".", 1)[0])
    return output & SDK_NAMES


def _channels(actx: ArchContext, graph: Graph) -> tuple[str | None, dict[str, str], dict[str, str]]:
    classification = actx.out.get("classification", {})
    groups = classification.get("groups", []) if isinstance(classification, dict) else []
    runtime = actx.out.get("runtime", {})
    anchors = runtime.get("anchors", []) if isinstance(runtime, dict) else []
    anchor_groups = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        for value in group.get("anchors", []):
            anchor_groups[str(value)] = str(group.get("id"))
    packages: dict[str, str] = {}
    package_sdks: dict[str, str] = {}
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        entry = anchor.get("entry")
        if not isinstance(entry, str):
            continue
        name = graph.by_path.get(entry)
        item = graph.modules.get(name) if name else None
        sdks = _sdk_imports(item)
        if not sdks:
            continue
        parts = Path(entry).parts
        package = parts[0] if len(parts) > 1 else Path(entry).stem
        group_id = anchor_groups.get(_anchor_id(anchor))
        if group_id is None:
            continue
        packages[package] = group_id
        package_sdks[package] = sorted(sdks)[0]
    valid_groups = {
        group_id
        for group_id in set(packages.values())
        if sum(value == group_id for value in packages.values()) >= 2
    }
    if not valid_groups:
        return None, {}, {}
    group_id = sorted(valid_groups)[0]
    selected = {package: value for package, value in packages.items() if value == group_id}
    return group_id, selected, {package: package_sdks[package] for package in selected}


def _closure(graph: Graph, start: str, package: str) -> set[str]:
    seen = set()
    pending = deque([start])
    while pending:
        name = pending.popleft()
        if name in seen or not (name == package or name.startswith(package + ".")):
            continue
        seen.add(name)
        pending.extend(
            edge.target
            for edge in graph.edges
            if edge.source == name and not edge.type_checking and edge.target not in seen
        )
    return seen


def _interface_modules(
    actx: ArchContext,
    graph: Graph,
    packages: set[str],
    assignment: dict[str, str],
) -> dict[str, set[str]]:
    runtime = actx.out.get("runtime", {})
    anchors = runtime.get("anchors", []) if isinstance(runtime, dict) else []
    result = {package: set() for package in packages}
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        entry = anchor.get("entry")
        name = graph.by_path.get(entry) if isinstance(entry, str) else None
        if name is None:
            continue
        package = name.split(".", 1)[0]
        if package in packages:
            result[package].update(_closure(graph, name, package))
    for name, item in graph.modules.items():
        package = name.split(".", 1)[0]
        if package not in packages or item.tree is None:
            continue
        for node in ast.walk(item.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if isinstance(target, ast.Attribute):
                    result[package].add(name)
    for package in result:
        result[package] = {
            name
            for name in result[package]
            if assignment.get(graph.modules[name].path) not in {"core", "adapters"}
        }
    return result


def _constants_only(tree: ast.Module | None) -> bool:
    if tree is None:
        return False
    meaningful = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]
    return bool(meaningful) and all(
        isinstance(node, (ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom))
        or isinstance(node, ast.ClassDef)
        and all(
            isinstance(child, (ast.Assign, ast.AnnAssign, ast.Pass))
            for child in node.body
        )
        for node in meaningful
    )


def _functions(graph: Graph, names: set[str]) -> dict[str, list[dict]]:
    output: dict[str, list[dict]] = defaultdict(list)
    for name in sorted(names):
        item = graph.modules[name]
        if item.tree is None:
            continue
        source = item.data.decode("utf-8", "replace").splitlines()
        for node in ast.walk(item.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            clean = [
                line.strip()
                for line in source[node.lineno - 1 : getattr(node, "end_lineno", node.lineno)]
                if line.strip() and not line.lstrip().startswith("#")
            ]
            calls = []
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                    calls.append(child.func.attr)
            output[node.name].append(
                {"module": name, "path": item.path, "node": node, "lines": clean, "calls": calls}
            )
    return output


def _external_targets(graph: Graph, packages: set[str], direct_io: dict[str, set[str]]) -> set[str]:
    return {
        name
        for name, values in direct_io.items()
        if values and name.split(".", 1)[0] not in packages
    }


def _calls_client(graph: Graph, record: dict, targets: set[str]) -> bool:
    imports_client = any(
        edge.source == record["module"] and edge.target in targets
        for edge in graph.edges
    )
    return imports_client and bool(record["calls"])


def _same_name_pairs(
    graph: Graph,
    interfaces: dict[str, set[str]],
    targets: set[str],
) -> list[dict]:
    by_package = {package: _functions(graph, names) for package, names in interfaces.items()}
    packages = sorted(by_package)
    output = []
    for left_index, left_package in enumerate(packages):
        for right_package in packages[left_index + 1 :]:
            common = set(by_package[left_package]) & set(by_package[right_package])
            for name in sorted(common):
                excluded = None
                lowered = name.casefold()
                if name.startswith("__") and name.endswith("__"):
                    excluded = "dunder"
                elif name in {"main", "run", "register", "setup"}:
                    excluded = "entrypoint_or_registration"
                elif "keyboard" in lowered or "markup" in lowered:
                    excluded = "keyboard_factory"
                for left in by_package[left_package][name]:
                    for right in by_package[right_package][name]:
                        both = _calls_client(graph, left, targets) and _calls_client(graph, right, targets)
                        if not both and excluded is None:
                            continue
                        matcher = SequenceMatcher(None, left["lines"], right["lines"], autojunk=False)
                        ratio = matcher.ratio()
                        output.append(
                            {
                                "name": name,
                                "left": left["path"],
                                "right": right["path"],
                                "ratio": round(ratio, 6),
                                "diff_lines": max(len(left["lines"]), len(right["lines"])) - int(round(ratio * max(len(left["lines"]), len(right["lines"])))),
                                "both_call_client": both,
                                "excluded_kind": excluded,
                            }
                        )
    return sorted(
        output,
        key=lambda item: (
            item["left"],
            item["right"],
            item["name"],
            item["ratio"],
            item["diff_lines"],
            item["both_call_client"],
            item["excluded_kind"] or "",
        ),
    )


def _git_ignored(actx: ArchContext, path: str) -> bool:
    if not actx.vcs:
        return False
    return git(actx.root, "check-ignore", "-q", "--", path).rc == 0


def _runtime_tools(actx: ArchContext) -> tuple[list[dict], bool]:
    runtime = actx.out.get("runtime", {})
    anchors = runtime.get("anchors", []) if isinstance(runtime, dict) else []
    cached_meta = actx.cache.get("runtime_anchor_meta", [])
    meta = cached_meta if isinstance(cached_meta, list) else []
    output = []
    unsupported = False
    for index, anchor in enumerate(anchors):
        if not isinstance(anchor, dict):
            continue
        entry = anchor.get("entry")
        if not isinstance(entry, str):
            continue
        parts = Path(entry).parts
        tool = "scripts" in parts or ("management" in parts and "commands" in parts)
        if not tool:
            continue
        docker_ignored = False
        details = meta[index] if index < len(meta) and isinstance(meta[index], dict) else {}
        context_value = details.get("build_context", ".")
        context = actx.trees["primary"].path / str(context_value).removeprefix("./")
        for context in {actx.trees["primary"].path, context}:
            matcher = load_matcher(context)
            if matcher is None:
                unsupported = True
                continue
            try:
                rel = (actx.trees["primary"].path / entry).relative_to(context).as_posix()
            except ValueError:
                continue
            docker_ignored = docker_ignored or matcher(rel)
        output.append(
            {
                "source": _anchor_id(anchor),
                "target": entry,
                "ignored": _git_ignored(actx, entry),
                "dockerignored": docker_ignored,
            }
        )
    output.sort(
        key=lambda item: (
            item["source"],
            item["target"],
            item["ignored"],
            item["dockerignored"],
        )
    )
    return output, unsupported


def analyse(
    actx: ArchContext,
    graph: Graph,
    direct_io: dict[str, set[str]],
    assignment: dict[str, str],
) -> tuple[dict | None, list[dict], list[dict], dict, dict]:
    group_id, package_groups, _ = _channels(actx, graph)
    runtime_tools, unsupported = _runtime_tools(actx)
    if group_id is None:
        return (
            None,
            [],
            runtime_tools,
            {"applicable": False},
            {
                "applicable": False,
                "runtime_to_tools_edges": len(runtime_tools),
                "ignored_runtime_targets": sum(
                    item["ignored"] or item["dockerignored"]
                    for item in runtime_tools
                ),
                "dockerignore_unsupported": unsupported,
            },
        )
    packages = set(package_groups)
    cross = []
    shared = []
    sdk_hits = set()
    importers: dict[str, set[str]] = {package: set() for package in packages}
    constants = set()
    for edge in graph.edges:
        if edge.type_checking:
            continue
        source_item = graph.modules[edge.source]
        target_item = graph.modules[edge.target]
        if not actx.is_prod_path(source_item.path) or not actx.is_prod_path(target_item.path):
            continue
        source_package = edge.source.split(".", 1)[0]
        target_package = edge.target.split(".", 1)[0]
        if target_package not in packages or source_package == target_package:
            continue
        target_sdks = _sdk_imports(target_item)
        sdk_hits.update((edge.target, sdk) for sdk in target_sdks)
        record = {
            "source": source_item.path,
            "target": target_item.path,
            "target_sdk_imports": sorted(target_sdks),
        }
        if source_package in packages:
            cross.append(record)
        else:
            shared.append(record)
        importers[target_package].add(source_item.path)
        if _constants_only(target_item.tree):
            constants.add(target_item.path)

    interfaces = _interface_modules(actx, graph, packages, assignment)
    targets = _external_targets(graph, packages, direct_io)
    interface_edges = []
    for package, names in sorted(interfaces.items()):
        for source in sorted(names):
            for edge in graph.edges:
                if edge.source == source and edge.target in targets:
                    if edge.type_checking:
                        continue
                    interface_edges.append(
                        {
                            "channel": package,
                            "source": graph.modules[source].path,
                            "target": graph.modules[edge.target].path,
                        }
                    )
    cross.sort(
        key=lambda item: (
            item["source"],
            item["target"],
            tuple(item["target_sdk_imports"]),
        )
    )
    shared.sort(
        key=lambda item: (
            item["source"],
            item["target"],
            tuple(item["target_sdk_imports"]),
        )
    )
    interface_edges.sort(
        key=lambda item: (item["source"], item["target"], item["channel"])
    )
    pairs = _same_name_pairs(graph, interfaces, targets)
    channel_data = {
        "packages": sorted(packages),
        "group_id": group_id,
        "cross_channel_edges": cross,
        "shared_to_channel_edges": shared,
        "imported_sdk_count": len(sdk_hits),
        "importers_by_package": {key: sorted(value) for key, value in sorted(importers.items())},
        "constants_only_modules": sorted(constants),
        "same_name_pairs": pairs,
    }
    rule_a16 = {
        "cross_channel_edges": len(cross),
        "edges_without_target_sdk": sum(
            not item["target_sdk_imports"] for item in cross
        ),
        "targets_without_sdk": sorted(
            {
                item["target"]
                for item in cross
                if not item["target_sdk_imports"]
            }
        )[:20],
        "constants_only_modules": len(constants),
        "shared_to_channel_edges": len(shared),
    }
    rule_a17 = {
        "interface_to_client_edges": len(interface_edges),
        "diverged_pairs": sum(item["excluded_kind"] is None and item["ratio"] < 0.95 for item in pairs),
        "runtime_to_tools_edges": len(runtime_tools),
        "ignored_runtime_targets": sum(item["ignored"] or item["dockerignored"] for item in runtime_tools),
        "dockerignore_unsupported": unsupported,
    }
    return channel_data, interface_edges, runtime_tools, rule_a16, rule_a17
