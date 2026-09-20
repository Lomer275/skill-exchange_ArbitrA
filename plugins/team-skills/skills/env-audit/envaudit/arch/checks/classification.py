from collections import defaultdict, deque
from pathlib import Path
import re

from envaudit.arch import pyast
from envaudit.arch.context import ArchContext


KEY = "classification"
ORDER = 30
DATED_NAME = re.compile(
    r"(?<!\d)20\d{2}[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?!\d)"
)
MANIFEST_NAMES = {
    "pyproject.toml",
    "setup.py",
    "package.json",
    "composer.json",
    "manage.py",
}
CODE_EXTENSIONS = frozenset(
    {".py", ".php", ".js", ".jsx", ".ts", ".tsx", ".cs", ".sql", ".sh"}
)
CODE_ANCHOR_KINDS = frozenset({"web_app", "desktop", "php_host_plugin"})
RUNTIME_ANCHOR_KINDS = frozenset(
    {"dockerfile_cmd", "systemd_units", "cron_entries", "repo_unit"}
)


def _module_name(rel: str) -> str:
    path = Path(rel)
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_import(module: str, imported: str, modules: set[str]) -> str | None:
    if imported.startswith("."):
        level = len(imported) - len(imported.lstrip("."))
        suffix = imported[level:]
        package = module.split(".")[:-1]
        base = package[: max(0, len(package) - level + 1)]
        candidate = ".".join([*base, *([suffix] if suffix else [])])
    else:
        candidate = imported
    if candidate in modules:
        return candidate
    matches = sorted(
        item for item in modules if item == candidate or item.startswith(candidate + ".")
    )
    return matches[0] if matches else None


def _python_graph(
    actx: ArchContext, subprojects: list[str]
) -> tuple[dict[str, str], dict[str, set[str]], int, int, int]:
    by_rel = {}
    parsed = {}
    main_guards = 0
    loaders = 0
    init_dirs = set()
    loader_names = {
        "importlib.import_module",
        "spec_from_file_location",
        "importlib.util.spec_from_file_location",
        "__import__",
        "runpy.run_module",
        "runpy.run_path",
    }
    for entry in actx.code_files(exts=frozenset({".py"})):
        if (
            not actx.is_prod_path(entry.rel)
            or _in_subproject(entry.rel, subprojects)
        ):
            continue
        module = _module_name(entry.rel)
        if not module:
            continue
        by_rel[entry.rel] = module
        if Path(entry.rel).name == "__init__.py":
            init_dirs.add(Path(entry.rel).parent.as_posix())
        data = actx.read(entry)
        if data is None:
            continue
        tree = pyast.parse(data, entry.rel)
        if tree is None:
            continue
        parsed[module] = tree
        if actx.is_prod_path(entry.rel):
            main_guards += int(pyast.has_main_guard(tree))
        loaders += len(pyast.calls_named(tree, loader_names))

    modules = set(by_rel.values())
    graph = {module: set() for module in modules}
    for module, tree in parsed.items():
        for imported, _, _ in pyast.imports(tree):
            target = _resolve_import(module, imported, modules)
            if target is not None and target != module:
                graph[module].add(target)
    return by_rel, graph, main_guards, len(init_dirs), loaders


def _closure(start: str | None, graph: dict[str, set[str]]) -> set[str]:
    if start is None or start not in graph:
        return set()
    seen = set()
    pending = deque([start])
    while pending:
        module = pending.popleft()
        if module in seen:
            continue
        seen.add(module)
        pending.extend(sorted(graph.get(module, set()) - seen))
    return seen


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _anchor_id(anchor: dict) -> str:
    location = anchor.get("file") or anchor.get("entry") or "live"
    line = anchor.get("line")
    return f"{anchor.get('kind')}:{location}" + (f":{line}" if line else "")


def _groups(
    anchors: list[dict], by_rel: dict[str, str], graph: dict[str, set[str]]
) -> tuple[list[dict], list[str]]:
    candidates = []
    for anchor in anchors:
        entry = anchor.get("entry")
        if not isinstance(entry, str):
            continue
        if Path(entry).suffix.lower() == ".sh":
            continue
        candidates.append(anchor)
    has_runtime_anchor = any(
        anchor.get("kind") in RUNTIME_ANCHOR_KINDS
        or (
            anchor.get("kind") == "compose_services"
            and anchor.get("image_group") is not None
        )
        for anchor in anchors
    )
    if has_runtime_anchor:
        participating = [
            anchor
            for anchor in candidates
            if anchor.get("kind") not in CODE_ANCHOR_KINDS
        ]
        code_anchors = [
            anchor
            for anchor in candidates
            if anchor.get("kind") in CODE_ANCHOR_KINDS
        ]
    else:
        participating = list(candidates)
        code_anchors = []

    closures = []
    for anchor in participating:
        module = by_rel.get(anchor.get("entry", ""))
        closures.append(_closure(module, graph))
    attachments = []
    unattached = []
    for anchor in code_anchors:
        entry = anchor.get("entry", "")
        module = by_rel.get(entry)
        exact = [
            index
            for index, candidate in enumerate(participating)
            if candidate.get("entry") == entry
        ]
        containing = [
            index
            for index in range(len(participating))
            if module is not None and module in closures[index]
        ]
        targets = exact or containing
        if not targets:
            unattached.append(entry)
            continue
        code_index = len(participating)
        participating.append(anchor)
        closures.append(_closure(module, graph))
        attachments.append((code_index, targets[0]))

    union = _UnionFind(len(participating))
    package_modules = {
        module
        for rel, module in by_rel.items()
        if Path(rel).name == "__init__.py"
    }
    for left in range(len(participating)):
        for right in range(left + 1, len(participating)):
            left_anchor = participating[left]
            right_anchor = participating[right]
            if has_runtime_anchor and any(
                anchor.get("kind") in CODE_ANCHOR_KINDS
                for anchor in (left_anchor, right_anchor)
            ):
                continue
            if not has_runtime_anchor and any(
                anchor.get("kind") == "web_app"
                and anchor.get("image_group") is None
                for anchor in (left_anchor, right_anchor)
            ):
                continue
            left_image = left_anchor.get("image_group")
            same_image = (
                left_image is not None
                and left_image == right_anchor.get("image_group")
            )
            shared_modules = (
                closures[left] & closures[right]
            ) - package_modules
            if same_image or bool(shared_modules):
                union.union(left, right)

    for code_index, target_index in attachments:
        union.union(code_index, target_index)

    members: dict[int, list[int]] = defaultdict(list)
    for index in range(len(participating)):
        members[union.find(index)].append(index)
    ordered = sorted(members.values(), key=lambda values: _anchor_id(participating[min(values)]))
    module_group = {}
    for group_index, values in enumerate(ordered, 1):
        for index in values:
            for module in closures[index]:
                if module not in package_modules:
                    module_group.setdefault(module, group_index)

    cross_counts = defaultdict(int)
    for source, targets in graph.items():
        source_group = module_group.get(source)
        for target in targets:
            target_group = module_group.get(target)
            if source_group and target_group and source_group != target_group:
                cross_counts[source_group] += 1

    output = []
    for group_index, values in enumerate(ordered, 1):
        packages = sorted(
            {
                module.split(".", 1)[0]
                for index in values
                for module in closures[index]
            }
        )
        output.append(
            {
                "id": f"group-{group_index}",
                "anchors": sorted(_anchor_id(participating[index]) for index in values),
                "packages": packages,
                "edges_to_other_groups": cross_counts[group_index],
            }
        )
    return output, sorted(set(unattached))


def _manifest(entry_rel: str) -> bool:
    name = Path(entry_rel).name
    lower = name.lower()
    return (
        name in MANIFEST_NAMES
        or (name.startswith("requirements") and name.endswith(".txt"))
        or name.endswith(".csproj")
        or name.startswith("Dockerfile")
        or (lower.startswith("docker-compose") and lower.endswith((".yml", ".yaml")))
    )


def _in_subproject(rel: str, subprojects: list[str]) -> bool:
    return any(rel == path or rel.startswith(path + "/") for path in subprojects)


def _trace(
    trace: list[dict], step: int | str, condition: str, values: dict, matched: bool
) -> bool:
    trace.append(
        {
            "step": step,
            "condition": condition,
            "values": values,
            "matched": matched,
        }
    )
    return matched


def _cron_agent(anchors: list[dict]) -> bool:
    if len(anchors) < 2 or any(
        anchor.get("kind") not in {"cron_entries", "systemd_units", "repo_unit"}
        for anchor in anchors
    ):
        return False
    entries = [anchor.get("entry") for anchor in anchors]
    if any(not isinstance(entry, str) for entry in entries):
        return False
    packages = {Path(entry).parts[0] for entry in entries if Path(entry).parts}
    return len(packages) == 1


def run(actx: ArchContext) -> None:
    cached_subprojects = actx.cache.get("subprojects", [])
    subprojects = (
        list(cached_subprojects) if isinstance(cached_subprojects, list) else []
    )
    files = [
        entry
        for entry in actx.files()
        if not _in_subproject(entry.rel, subprojects)
    ]
    python_files = [
        entry
        for entry in actx.code_files(exts=frozenset({".py"}))
        if actx.is_prod_path(entry.rel)
        and not _in_subproject(entry.rel, subprojects)
    ]
    by_rel, graph, main_guards, init_dirs, loaders = _python_graph(
        actx, subprojects
    )
    manifests = sum(1 for entry in files if _manifest(entry.rel))
    dated = sum(1 for entry in python_files if DATED_NAME.search(Path(entry.rel).name))
    scripts = {
        "manifests": manifests,
        "py_files": len(python_files),
        "dated_share": round(dated / len(python_files), 6) if python_files else 0.0,
        "main_guard_share": round(main_guards / len(python_files), 6) if python_files else 0.0,
        "init_dirs": init_dirs,
        "static_edges": sum(len(targets) for targets in graph.values()),
        "importlib_loaders": loaders,
    }
    runtime = actx.out.get("runtime", {})
    anchors = runtime.get("anchors", []) if isinstance(runtime, dict) else []
    anchors = [anchor for anchor in anchors if isinstance(anchor, dict)]
    groups, unattached_code_anchors = _groups(anchors, by_rel, graph)
    code_files = sum(
        1
        for entry in actx.code_files(exts=CODE_EXTENSIONS)
        if not _in_subproject(entry.rel, subprojects)
    )
    trace = []
    project_type = "mixed"
    subtype = None
    calibrated = False

    no_code_or_anchors = code_files == 0 and not anchors
    if _trace(
        trace,
        1,
        "code_files == 0 and anchors == 0",
        {"code_files": code_files, "anchors": len(anchors)},
        no_code_or_anchors,
    ):
        project_type = "docs"
    else:
        integration = (
            manifests == 0
            and len(python_files) >= 20
            and scripts["dated_share"] >= 0.5
            and scripts["main_guard_share"] >= 0.8
        )
        if _trace(
            trace,
            2,
            "manifests == 0 and py_files >= 20 and dated_share >= 0.50 and main_guard_share >= 0.80",
            dict(scripts),
            integration,
        ):
            project_type = "integration-scripts"
            calibrated = True
        elif _trace(
            trace,
            3,
            "runtime anchors present",
            {"anchors": len(anchors), "groups": len(groups)},
            bool(anchors),
        ):
            project_type = "application"
            calibrated = True
            kinds = {anchor.get("kind") for anchor in anchors}
            only_plugin = kinds == {"php_host_plugin"}
            if _trace(trace, "3.1", "only php_host_plugin anchors", {"kinds": sorted(kinds)}, only_plugin):
                subtype = "plugin-in-host"
            elif _trace(trace, "3.2", "only cron or timer anchors on one package", {"anchors": len(anchors)}, _cron_agent(anchors)):
                subtype = "cron-agent"
            else:
                client_server = "desktop" in kinds and bool(
                    kinds & {"web_app", "dockerfile_cmd"}
                )
                if _trace(trace, "3.3", "web or docker plus desktop", {"kinds": sorted(kinds)}, client_server):
                    subtype = "client-server"
                else:
                    edge_count = sum(group["edges_to_other_groups"] for group in groups)
                    multi = len(groups) >= 2 and edge_count == 0
                    if _trace(trace, "3.4", "at least two runtime groups with zero cross edges", {"groups": len(groups), "edges": edge_count}, multi):
                        subtype = "multi-app"
                    else:
                        _trace(trace, "3.5", "application fallback", {"groups": len(groups)}, True)
                        subtype = "service"
        else:
            library = any(
                Path(entry.rel).name in {"pyproject.toml", "setup.py"}
                for entry in files
            )
            if _trace(trace, 4, "pyproject.toml or setup.py present", {"manifest": library}, library):
                project_type = "library"
            else:
                _trace(trace, 5, "fallback", {}, True)

    actx.out[KEY] = {
        "type": project_type,
        "subtype": subtype,
        "calibrated": calibrated,
        "decision_trace": trace,
        "signals": {
            "scripts": scripts,
            "anchors": {"count": len(anchors), "kinds": sorted({str(anchor.get("kind")) for anchor in anchors})},
        },
        "groups": groups,
        "unattached_code_anchors": unattached_code_anchors,
        "subprojects": subprojects,
        "size_tier": None,
        "frozen_zones": [],
        "dormant_repo": False,
        "layers_declared": None,
    }
