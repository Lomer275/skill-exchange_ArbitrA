import ast
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from envaudit.arch import pyast
from envaudit.arch.context import ArchContext


KEY = "scripts_collection"
ORDER = 95
GOD_LINES = 800
FLAT_FILES = 1000
DEAD_DAYS = 180
MAX_ANALYSED_BYTES = 20 * 1024 * 1024
SAMPLE_MIN_BYTES = 2 * 1024 * 1024
CODE_EXTENSIONS = frozenset(
    {".py", ".php", ".js", ".jsx", ".ts", ".tsx", ".cs", ".sh", ".bash", ".zsh"}
)
DATA_EXTENSIONS = frozenset(
    {".json", ".jsonl", ".csv", ".tsv", ".db", ".sqlite", ".sql", ".xml", ".yaml", ".yml"}
)
DATED_NAME = re.compile(
    r"(?<!\d)20\d{2}[-_.]?(?:0[1-9]|1[0-2])[-_.]?(?:0[1-9]|[12]\d|3[01])(?!\d)"
)
BAK_DATE = re.compile(r"\.bak_20\d{6}$", re.IGNORECASE)
LOADER_NAMES = frozenset(
    {
        "importlib.util.spec_from_file_location",
        "spec_from_file_location",
        "importlib.import_module",
        "import_module",
        "runpy.run_path",
        "run_path",
        "__import__",
    }
)
LOADER_MARKERS = (b"importlib", b"spec_from_file_location", b"run_path", b"__import__")


def _line_count(data: bytes) -> int:
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def _digest(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _data_shaped(data: bytes, size: int) -> bool:
    if size >= SAMPLE_MIN_BYTES:
        window = 256 * 1024
        blocks = [
            data[offset : offset + window]
            for offset in (
                0,
                max(0, size // 2 - window // 2),
                max(0, size - window),
            )
        ]
    else:
        blocks = [data]
    lines = 0
    literal = 0
    for block in blocks:
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lines += 1
            literal += int(
                stripped[:1] in {b"'", b'"', b"[", b"{", b"(", b"]", b"}"}
                or stripped[:1].isdigit()
                or b"=>" in stripped
            )
    return bool(lines) and literal / lines >= 0.8


def _function_count(data: bytes, suffix: str, rel: str) -> int:
    if suffix == ".py":
        tree = pyast.parse(data, rel)
        return (
            sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree))
            if tree is not None
            else 0
        )
    if suffix == ".php":
        from envaudit.arch.php_lexer import strip_php

        data = strip_php(data)
        return len(re.findall(rb"\bfunction\s+(?:&\s*)?[A-Za-z_]\w*\s*\(", data, re.IGNORECASE))
    return len(re.findall(rb"\b(?:function\s+)?[A-Za-z_]\w*\s*\([^;{}]*\)\s*(?:\{|=>)", data))


def _module_name(rel: str) -> str:
    path = Path(rel).with_suffix("")
    parts = list(path.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_python_import(module: str, imported: str, modules: set[str]) -> str | None:
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
    matches = sorted(item for item in modules if item.startswith(candidate + "."))
    return matches[0] if matches else None


def _live_paths(actx: ArchContext) -> set[str]:
    starts = set()
    for unit in actx.live_units() or []:
        entry = unit.get("entry") if isinstance(unit, dict) else None
        if isinstance(entry, str):
            starts.add(entry.lstrip("./"))
    runtime = actx.out.get("runtime", {})
    anchors = runtime.get("anchors", []) if isinstance(runtime, dict) else []
    for anchor in anchors:
        entry = anchor.get("entry") if isinstance(anchor, dict) else None
        if anchor.get("live") is True and isinstance(entry, str):
            starts.add(entry.lstrip("./"))

    by_module = {}
    parsed = {}
    for entry in actx.code_files(exts=frozenset({".py"})):
        module = _module_name(entry.rel)
        if not module:
            continue
        by_module[module] = entry.rel
        data = actx.read(entry)
        if data is not None:
            tree = pyast.parse(data, entry.rel)
            if tree is not None:
                parsed[module] = tree
    modules = set(by_module)
    graph = {module: set() for module in modules}
    for module, tree in parsed.items():
        for imported, _, _ in pyast.imports(tree):
            target = _resolve_python_import(module, imported, modules)
            if target is not None:
                graph[module].add(target)

    rel_to_module = {rel: module for module, rel in by_module.items()}
    pending = deque(rel_to_module[rel] for rel in starts if rel in rel_to_module)
    seen_modules = set()
    while pending:
        module = pending.popleft()
        if module in seen_modules:
            continue
        seen_modules.add(module)
        pending.extend(sorted(graph.get(module, set()) - seen_modules))
    starts.update(by_module[module] for module in seen_modules)
    return starts


def _static_references(actx: ArchContext) -> set[str]:
    entries = {
        entry.rel: entry
        for entry in actx.code_files(exts=frozenset({".py"}))
    }
    by_module = {
        _module_name(rel): rel for rel in entries if _module_name(rel)
    }
    modules = set(by_module)
    output = set()
    for module, rel in by_module.items():
        entry = entries[rel]
        data = actx.read(entry)
        tree = pyast.parse(data, rel) if data is not None else None
        if tree is None:
            continue
        for imported, _, _ in pyast.imports(tree):
            target = _resolve_python_import(module, imported, modules)
            if target is not None:
                output.add(by_module[target])
    return output


def _deployed(rel: str, live_paths: set[str]) -> bool:
    return rel == "local" or rel.startswith("local/") or rel in live_paths


def _god_files(actx: ArchContext, live_paths: set[str]) -> list[dict]:
    candidates: dict[int, list[tuple[object, bytes, int]]] = defaultdict(list)
    for entry in actx.code_files(exts=CODE_EXTENSIONS):
        if not _deployed(entry.rel, live_paths) or DATED_NAME.search(Path(entry.rel).name):
            continue
        if entry.size > MAX_ANALYSED_BYTES:
            continue
        data = actx.read(entry, max_bytes=MAX_ANALYSED_BYTES)
        if data is None:
            continue
        lines = _line_count(data)
        if lines <= GOD_LINES or _data_shaped(data, entry.size):
            continue
        candidates[entry.size].append((entry, data, lines))

    output = []
    for same_size in candidates.values():
        groups: dict[str | None, list[tuple[object, bytes, int]]] = defaultdict(list)
        for candidate in same_size:
            digest = _digest(candidate[1]) if len(same_size) >= 2 else None
            groups[digest].append(candidate)
        for copies in groups.values():
            copies.sort(key=lambda item: item[0].rel)
            entry, data, lines = copies[0]
            output.append(
                {
                    "path": entry.rel,
                    "lines": lines,
                    "functions": _function_count(
                        data, Path(entry.rel).suffix.lower(), entry.rel
                    ),
                    "copies": len(copies),
                }
            )
    return sorted(output, key=lambda item: (-item["lines"], item["path"]))


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _path_expr(node: ast.AST, source: Path) -> Path | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        candidate = Path(node.value).expanduser()
        return candidate if candidate.is_absolute() else source.parent / candidate
    if isinstance(node, ast.Name) and node.id == "__file__":
        return source
    if isinstance(node, ast.Call):
        name = _call_name(node.func)
        if name in {"Path", "pathlib.Path"} and len(node.args) == 1:
            return _path_expr(node.args[0], source)
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"resolve", "absolute"}:
            return _path_expr(node.func.value, source)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "joinpath":
            base = _path_expr(node.func.value, source)
            if base is None:
                return None
            for argument in node.args:
                if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
                    return None
                base /= argument.value
            return base
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        base = _path_expr(node.value, source)
        return base.parent if base is not None else None
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
        base = _path_expr(node.value.value, source)
        index = node.slice.value if isinstance(node.slice, ast.Constant) else None
        if base is not None and isinstance(index, int) and index >= 0:
            try:
                return base.parents[index]
            except IndexError:
                return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _path_expr(node.left, source)
        if left is not None and isinstance(node.right, ast.Constant) and isinstance(node.right.value, str):
            return left / node.right.value
    return None


def _relative_target(path: Path, root: Path) -> str:
    normalized = Path(os.path.abspath(path))
    try:
        return normalized.relative_to(Path(os.path.abspath(root))).as_posix()
    except ValueError:
        return f"<outside_root>/{normalized.name}"


def _module_targets(value: str, source: Path, root: Path) -> list[Path]:
    rel = Path(*value.split("."))
    return [root / rel.with_suffix(".py"), root / rel / "__init__.py", source.parent / rel.with_suffix(".py")]


def _fan_in_live_paths(actx: ArchContext) -> tuple[set[str], set[str]]:
    entries = {
        unit.get("entry").lstrip("./")
        for unit in (actx.live_units() or [])
        if isinstance(unit, dict) and isinstance(unit.get("entry"), str)
    }
    try:
        from envaudit.arch.closure import import_closure
    except ImportError:
        directories = {Path(entry).parent.as_posix() for entry in entries}
        return entries, directories

    live_paths = set()
    for entry in entries:
        live_paths.update(import_closure(actx, entry))
    return live_paths, set()


def _loaders(actx: ArchContext, live_paths: set[str]) -> tuple[dict, set[str]]:
    root = actx.trees["primary"].path
    local_modules = pyast.local_modules(actx)
    fan_in_live_paths, fan_in_live_dirs = _fan_in_live_paths(actx)
    missing = []
    total = 0
    live_loaders = 0
    importers: dict[str, set[str]] = defaultdict(set)
    live_importers: dict[str, set[str]] = defaultdict(set)
    referenced = set()
    for entry in actx.code_files(exts=frozenset({".py"})):
        data = actx.read(entry)
        if data is None or not any(marker in data for marker in LOADER_MARKERS):
            continue
        tree = pyast.parse(data, entry.rel)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            if name not in LOADER_NAMES:
                continue
            argument_index = 1 if name.endswith("spec_from_file_location") else 0
            if len(node.args) <= argument_index:
                total += 1
                live_loaders += int(entry.rel in live_paths)
                continue
            argument = node.args[argument_index]
            if (
                name.endswith(("import_module", "__import__"))
                and isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
                and argument.value.split(".", 1)[0] not in local_modules
            ):
                continue
            total += 1
            is_live = entry.rel in live_paths
            live_loaders += int(is_live)
            candidates = []
            if name.endswith(("import_module", "__import__")) and isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                candidates = _module_targets(argument.value, entry.path, root)
            else:
                resolved = _path_expr(argument, entry.path)
                if resolved is not None:
                    candidates = [resolved]
            if not candidates:
                continue
            existing = next((candidate for candidate in candidates if candidate.is_file()), None)
            target = existing or candidates[0]
            display = _relative_target(target, root)
            referenced.add(display)
            if existing is None:
                missing.append(
                    {
                        "loader": entry.rel,
                        "line": node.lineno,
                        "target": display,
                        "live": is_live,
                    }
                )
            else:
                importers[display].add(entry.rel)
                if (
                    entry.rel in fan_in_live_paths
                    or Path(entry.rel).parent.as_posix() in fan_in_live_dirs
                ):
                    live_importers[display].add(entry.rel)

    fan_in = [
        {
            "target": target,
            "loaders": len(paths),
            "live_loaders": len(live_importers[target]),
        }
        for target, paths in importers.items()
        if len(paths) >= 2
    ]
    fan_in.sort(key=lambda item: (-item["loaders"], item["target"]))
    return (
        {
            "targets_total": total,
            "targets_missing": sorted(missing, key=lambda item: (item["loader"], item["line"], item["target"])),
            "live_loaders": live_loaders,
            "fan_in_top": fan_in[:10],
        },
        referenced,
    )


def _infra_helpers(actx: ArchContext, live_paths: set[str]) -> dict:
    grouped: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    raw = 0
    for entry in actx.code_files(exts=frozenset({".py"})):
        if entry.rel not in live_paths or DATED_NAME.search(Path(entry.rel).name):
            continue
        data = actx.read(entry)
        tree = pyast.parse(data, entry.rel) if data is not None else None
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            raw += 1
            normalized = ast.dump(node, annotate_fields=True, include_attributes=False)
            digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
            grouped[digest][node.name].add(entry.rel)
    groups = []
    for names in grouped.values():
        for name, paths in names.items():
            if len(paths) >= 3:
                groups.append({"name": name, "copies": len(paths)})
    groups.sort(key=lambda item: (-item["copies"], item["name"]))
    return {"groups": groups, "raw_defs_total": raw}


def _flat_dirs(actx: ArchContext) -> list[dict]:
    grouped: dict[str, list[object]] = defaultdict(list)
    for entry in actx.files():
        parent = Path(entry.rel).parent.as_posix()
        grouped[parent].append(entry)
    now = datetime.now(timezone.utc).timestamp()
    output = []
    for directory, entries in grouped.items():
        if len(entries) <= FLAT_FILES:
            continue
        newest = max(entry.mtime for entry in entries)
        output.append(
            {
                "path": directory,
                "direct_files": len(entries),
                "bytes": sum(entry.size for entry in entries),
                "has_code_files": any(Path(entry.rel).suffix.lower() in CODE_EXTENSIONS for entry in entries),
                "newest_mtime_days": max(0, int((now - newest) // 86400)),
            }
        )
    return sorted(output, key=lambda item: (-item["direct_files"], item["path"]))


def _n8n(data: bytes) -> bool:
    if b'"nodes"' not in data or b'"connections"' not in data:
        return False
    try:
        document = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return isinstance(document, dict) and isinstance(document.get("nodes"), list) and "connections" in document


def _effective_suffix(rel: str) -> str:
    name = Path(rel).name
    if BAK_DATE.search(name):
        name = BAK_DATE.sub("", name)
    return Path(name).suffix.lower()


def _data_vs_code(actx: ArchContext) -> dict:
    data_bytes = 0
    code_bytes = 0
    data_shaped = []
    n8n_workflows = []
    for entry in actx.files():
        suffix = _effective_suffix(entry.rel)
        if suffix == ".json" and entry.size <= MAX_ANALYSED_BYTES:
            content = actx.read(entry, max_bytes=MAX_ANALYSED_BYTES)
            if content is not None and _n8n(content):
                code_bytes += entry.size
                n8n_workflows.append(entry.rel)
                continue
        if suffix in CODE_EXTENSIONS:
            content = (
                actx.read(entry, max_bytes=MAX_ANALYSED_BYTES)
                if entry.size <= MAX_ANALYSED_BYTES
                else None
            )
            if content is not None and _data_shaped(content, entry.size):
                data_bytes += entry.size
                data_shaped.append(entry.rel)
            else:
                code_bytes += entry.size
        elif suffix in DATA_EXTENSIONS:
            data_bytes += entry.size
    return {
        "data_bytes": data_bytes,
        "code_bytes": code_bytes,
        "data_shaped": sorted(data_shaped),
        "n8n_workflows": sorted(n8n_workflows),
    }


def _self_nested(actx: ArchContext) -> list[str]:
    output = set()
    for entry in actx.files():
        parts = Path(entry.rel).parts
        for index, (left, right) in enumerate(zip(parts, parts[1:])):
            if left == right:
                output.add(Path(*parts[: index + 2]).as_posix())
                break
    return sorted(output)


def _doc_metric(actx: ArchContext) -> dict:
    handoffs = 0
    changelogs = 0
    for entry in actx.files():
        path = Path(entry.rel)
        if path.suffix.lower() != ".md":
            continue
        lowered = path.stem.lower()
        handoffs += int("handoff" in lowered)
        changelogs += int("changelog" in lowered)
    return {"handoff_md": handoffs, "changelog_md": changelogs, "total": handoffs + changelogs}


def _dead_dirs(actx: ArchContext, referenced: set[str], live_paths: set[str]) -> list[dict]:
    grouped: dict[str, list[object]] = defaultdict(list)
    for entry in actx.files():
        parts = Path(entry.rel).parts
        if len(parts) > 1:
            grouped[parts[0]].append(entry)
    now = datetime.now(timezone.utc).timestamp()
    churn = actx.churn()
    output = []
    all_refs = referenced | live_paths
    for directory, entries in sorted(grouped.items()):
        importers = sum(path == directory or path.startswith(directory + "/") for path in all_refs)
        if importers:
            continue
        if actx.vcs:
            if directory.lower() not in {"docs", "scripts"} or churn is None:
                continue
            stamps = [churn[entry.rel][0] for entry in entries if entry.rel in churn]
            if not stamps:
                continue
            age = max(0, int((now - max(stamps)) // 86400))
        else:
            age = max(0, int((now - max(entry.mtime for entry in entries)) // 86400))
        if age > DEAD_DAYS:
            output.append({"path": directory, "newest_change_days": age, "importers": 0})
    return output


def _normalized_lines(data: bytes | None) -> set[str]:
    if data is None:
        return set()
    lines = data.decode("utf-8", "replace").splitlines()
    return {" ".join(line.split()) for line in lines if line.strip()}


def _instruction_overlap(actx: ArchContext) -> int:
    entries = {entry.rel: entry for entry in actx.files()}
    claude = entries.get("CLAUDE.md")
    agents = entries.get("AGENTS.md")
    return len(
        _normalized_lines(actx.read(claude) if claude is not None else None)
        & _normalized_lines(actx.read(agents) if agents is not None else None)
    )


def _defaults() -> dict:
    return {
        "loaders": {"targets_total": 0, "targets_missing": [], "live_loaders": 0, "fan_in_top": []},
        "infra_helper_defs": {"groups": [], "raw_defs_total": 0},
        "god_files_deployed": [],
        "data_vs_code": {"data_bytes": 0, "code_bytes": 0, "data_shaped": [], "n8n_workflows": []},
        "instruction_overlap": 0,
        "flat_dirs": [],
        "self_nested_paths": [],
        "dead_dirs": [],
        "doc_duplicates_metric": {"handoff_md": 0, "changelog_md": 0, "total": 0},
    }


def run(actx: ArchContext) -> None:
    section = actx.out.setdefault(KEY, {})
    if not isinstance(section, dict):
        actx.error(KEY, "invalid_existing_section")
        return
    for name, value in _defaults().items():
        section.setdefault(name, value)

    classification = actx.out.get("classification", {})
    project_type = classification.get("type") if isinstance(classification, dict) else None
    applicable = project_type in {"integration-scripts", "mixed"}
    if not applicable:
        for number in range(5, 16):
            actx.rule_inputs[f"I{number}"] = {"applicable": False}
        return

    live_paths = _live_paths(actx)
    god_files = _god_files(actx, live_paths)
    loaders, referenced = _loaders(actx, live_paths)
    referenced.update(_static_references(actx))
    helpers = _infra_helpers(actx, live_paths)
    flat_dirs = _flat_dirs(actx)
    data_vs_code = _data_vs_code(actx)
    nested = _self_nested(actx)
    docs = _doc_metric(actx)
    dead_dirs = _dead_dirs(actx, referenced, live_paths)
    overlap = _instruction_overlap(actx)
    values = {
        "god_files_deployed": god_files,
        "loaders": loaders,
        "infra_helper_defs": helpers,
        "flat_dirs": flat_dirs,
        "data_vs_code": data_vs_code,
        "self_nested_paths": nested,
        "doc_duplicates_metric": docs,
        "dead_dirs": dead_dirs,
        "instruction_overlap": overlap,
    }
    section.update(values)

    hygiene = actx.out.get("hygiene", {})
    root_files = hygiene.get("root_files", {}) if isinstance(hygiene, dict) else {}
    broken = hygiene.get("broken_names", []) if isinstance(hygiene, dict) else []
    root_broken = [path for path in broken if len(Path(path).parts) == 1]
    large = root_files.get("large_over_10mb", []) if isinstance(root_files, dict) else []
    actx.rule_inputs["I5"] = {"applicable": True, "count": len(god_files)}
    actx.rule_inputs["I6"] = {
        "applicable": True,
        "targets_missing": len(loaders["targets_missing"]),
        "live_loaders": loaders["live_loaders"],
    }
    actx.rule_inputs["I7"] = {"applicable": True, "groups": len(helpers["groups"])}
    actx.rule_inputs["I8"] = {"applicable": True, "count": len(flat_dirs)}
    actx.rule_inputs["I9"] = {
        "applicable": True,
        "see": "hygiene",
        "large_over_10mb": len(large),
        "broken_names": len(root_broken),
    }
    actx.rule_inputs["I10"] = {
        "applicable": True,
        "see": "hygiene.broken_names",
        "count": len(broken),
    }
    actx.rule_inputs["I11"] = {"applicable": True, **data_vs_code}
    actx.rule_inputs["I12"] = {"applicable": True, "count": len(nested)}
    actx.rule_inputs["I13"] = {"applicable": True, "metric_only": True, "count": docs["total"]}
    actx.rule_inputs["I14"] = {"applicable": True, "metric_only": True, "count": len(dead_dirs)}
    actx.rule_inputs["I15"] = {"applicable": True, "count": overlap}
