import ast
from collections import Counter
from pathlib import Path
import re

from envaudit.arch import pyast
from envaudit.arch.context import ArchContext


KEY = "schema_db"
ORDER = 65
ALEMBIC_REVISION = re.compile(
    r"(?m)^revision(?:\s*:\s*[^=\n]+)?\s*=\s*['\"]([^'\"]+)['\"]"
)
ALEMBIC_DOWN = re.compile(r"(?m)^down_revision(?:\s*:\s*[^=\n]+)?\s*=\s*(.+)$")
DJANGO_MIGRATION = re.compile(
    r"class\s+Migration\s*\(\s*migrations\.Migration\s*\)"
)
UPGRADE = re.compile(r"\b(?:alembic\s+upgrade|manage\.py\s+migrate)\b", re.I)
CI_GUARD = re.compile(r"\b(?:makemigrations\s+--check|alembic\s+check)\b", re.I)
CREATE_TABLE = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:[`\"\[]?[A-Za-z_]\w*[`\"\]]?\.)?"
    r"[`\"\[]?([A-Za-z_]\w*)[`\"\]]?",
    re.I,
)


def _text(actx: ArchContext, entry) -> str | None:
    data = actx.read(entry)
    return data.decode("utf-8", "replace") if data is not None else None


def _migration_dirs(actx: ArchContext) -> list[dict]:
    entries = actx.files()
    groups: dict[tuple[str, str], dict] = {}
    alembic_roots = []
    for entry in entries:
        if Path(entry.rel).name != "alembic.ini":
            continue
        text = _text(actx, entry)
        if text is None:
            continue
        match = re.search(r"(?m)^\s*script_location\s*=\s*([^#\r\n]+)", text)
        if match is None:
            continue
        value = match.group(1).strip()
        if "%(here)s" in value:
            path = Path(value.replace("%(here)s", Path(entry.rel).parent.as_posix()))
        else:
            path = Path(entry.rel).parent / value
        normalized = Path(str(path)).as_posix().removeprefix("./")
        alembic_roots.append(normalized)
        groups[(normalized, "alembic")] = {
            "path": normalized,
            "tool": "alembic",
            "found_by": "alembic_ini",
            "revision_ids": [],
            "numbers": [],
            "revisions": 0,
            "merge_migrations": 0,
        }

    for entry in entries:
        if Path(entry.rel).suffix.lower() != ".py":
            continue
        text = _text(actx, entry)
        if text is None:
            continue
        revision = ALEMBIC_REVISION.search(text)
        down = ALEMBIC_DOWN.search(text)
        if revision and down:
            root = next(
                (
                    candidate
                    for candidate in sorted(alembic_roots, key=len, reverse=True)
                    if entry.rel == candidate or entry.rel.startswith(candidate + "/")
                ),
                Path(entry.rel).parent.as_posix(),
            )
            item = groups.setdefault(
                (root, "alembic"),
                {
                    "path": root,
                    "tool": "alembic",
                    "found_by": "content",
                    "revision_ids": [],
                    "numbers": [],
                    "revisions": 0,
                    "merge_migrations": 0,
                },
            )
            item["revisions"] += 1
            item["revision_ids"].append(revision.group(1))
            down_value = down.group(1).strip()
            if down_value.startswith(("(", "[")) or "merge" in Path(entry.rel).name.lower():
                item["merge_migrations"] += 1
        if DJANGO_MIGRATION.search(text):
            root = Path(entry.rel).parent.as_posix()
            item = groups.setdefault(
                (root, "django"),
                {
                    "path": root,
                    "tool": "django",
                    "found_by": "content",
                    "revision_ids": [],
                    "numbers": [],
                    "revisions": 0,
                    "merge_migrations": 0,
                },
            )
            item["revisions"] += 1
            number = re.match(r"(\d{4,})", Path(entry.rel).name)
            if number:
                item["numbers"].append(number.group(1))
            if "merge" in Path(entry.rel).stem.lower():
                item["merge_migrations"] += 1

    output = []
    for item in groups.values():
        values = item.pop("revision_ids") + item.pop("numbers")
        counts = Counter(values)
        item["duplicate_numbers"] = sorted(
            value for value, count in counts.items() if count > 1
        )
        output.append(item)
    return sorted(output, key=lambda item: (item["path"], item["tool"]))


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _is_startup(function: ast.AST) -> bool:
    if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    if function.name == "lifespan":
        return True
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = _call_name(decorator.func)
        if name and name.endswith("on_event") and any(
            isinstance(argument, ast.Constant) and argument.value == "startup"
            for argument in decorator.args
        ):
            return True
    return False


def _raises(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(node, ast.Raise) for node in ast.walk(handler))


def _function_facts(parsed: ast.Module) -> tuple[dict[int, str | None], set[str], dict[str, str]]:
    functions = {
        node.name: node
        for node in parsed.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    owners: dict[int, str | None] = {}
    for node in ast.walk(parsed):
        owners[id(node)] = None
    for name, function in functions.items():
        for node in ast.walk(function):
            owners[id(node)] = name
    startup = {name for name, function in functions.items() if _is_startup(function)}
    via = {name: name for name in startup}
    for startup_name in sorted(startup):
        for node in ast.walk(functions[startup_name]):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            if name in functions and name not in via:
                via[name] = f"{startup_name}->{name}"
    return owners, set(via), via


def _create_all_and_swallowed(actx: ArchContext) -> tuple[list[dict], list[dict]]:
    sites = []
    swallowed = []
    for entry in actx.code_files(exts=frozenset({".py"})):
        data = actx.read(entry)
        parsed = pyast.parse(data, entry.rel) if data is not None else None
        if parsed is None:
            continue
        owners, startup_functions, via = _function_facts(parsed)
        call_functions = {
            id(node.func)
            for node in ast.walk(parsed)
            if isinstance(node, ast.Call)
        }
        for node in ast.walk(parsed):
            if not isinstance(node, ast.Attribute) or node.attr != "create_all":
                continue
            owner = owners.get(id(node))
            in_startup = owner in startup_functions
            sites.append(
                {
                    "path": entry.rel,
                    "line": node.lineno,
                    "kind": "call" if id(node) in call_functions else "ref",
                    "in_startup": in_startup,
                    "in_startup_via": via.get(owner) if in_startup else None,
                }
            )
        for node in ast.walk(parsed):
            if not isinstance(node, ast.ExceptHandler) or _raises(node):
                continue
            caught = _call_name(node.type) if node.type is not None else None
            owner = owners.get(id(node))
            if caught == "Exception" and owner in startup_functions:
                swallowed.append(
                    {"path": entry.rel, "line": node.lineno, "function": owner}
                )
    return (
        sorted(sites, key=lambda item: (item["path"], item["line"])),
        sorted(swallowed, key=lambda item: (item["path"], item["line"])),
    )


def _is_command_file(rel: str) -> bool:
    path = Path(rel)
    lower = path.name.lower()
    return bool(
        lower.startswith("dockerfile")
        or "entrypoint" in lower
        or lower.startswith("docker-compose")
        or lower in {"compose.yml", "compose.yaml", ".gitlab-ci.yml"}
        or rel.startswith(".github/workflows/")
    )


def _commands_and_guard(actx: ArchContext) -> tuple[list[dict], bool]:
    invocations = []
    guard = False
    for entry in actx.files():
        if not _is_command_file(entry.rel):
            continue
        text = _text(actx, entry)
        if text is None:
            continue
        is_ci = entry.rel == ".gitlab-ci.yml" or entry.rel.startswith(
            ".github/workflows/"
        )
        for number, line in enumerate(text.splitlines(), 1):
            if UPGRADE.search(line):
                invocations.append({"path": entry.rel, "line": number})
            if is_ci and CI_GUARD.search(line):
                guard = True
    return invocations, guard


def _django_table(entry_rel: str, class_name: str) -> str:
    path = Path(entry_rel)
    parts = path.parts
    if path.name == "models.py":
        app = path.parent.name
    elif "models" in path.parent.parts:
        index = max(
            position
            for position, part in enumerate(path.parent.parts)
            if part == "models"
        )
        app = path.parent.parts[index - 1] if index else "app"
    else:
        app = parts[-2] if len(parts) > 1 else "app"
    return f"{app.lower()}_{class_name.lower()}"


def _tables_and_sql(actx: ArchContext) -> tuple[list[str], list[str], list[str]]:
    orm = set()
    sql = set()
    sql_files = []
    for entry in actx.files():
        suffix = Path(entry.rel).suffix.lower()
        data = actx.read(entry)
        if data is None:
            continue
        if suffix == ".sql":
            sql_files.append(entry.rel)
            text = data.decode("utf-8", "replace")
            sql.update(match.group(1).lower() for match in CREATE_TABLE.finditer(text))
        elif suffix == ".py":
            parsed = pyast.parse(data, entry.rel)
            if parsed is None:
                continue
            for node in ast.walk(parsed):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    value = node.value
                    if any(isinstance(target, ast.Name) and target.id == "__tablename__" for target in targets):
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            orm.add(value.value.lower())
                if isinstance(node, ast.ClassDef) and any(
                    (_call_name(base) or "").endswith("Model") for base in node.bases
                ):
                    orm.add(_django_table(entry.rel, node.name))
    return sorted(orm), sorted(sql), sorted(sql_files)


def run(actx: ArchContext) -> None:
    migration_dirs = _migration_dirs(actx)
    create_all_sites, swallowed = _create_all_and_swallowed(actx)
    invocations, guard = _commands_and_guard(actx)
    orm_tables, sql_tables, sql_files = _tables_and_sql(actx)
    output = {
        "create_all_sites": create_all_sites,
        "migration_dirs": migration_dirs,
        "upgrade_invocations": invocations,
        "sql_files": sql_files,
        "orm_tables": orm_tables,
        "sql_tables": sql_tables,
        "orm_only": sorted(set(orm_tables) - set(sql_tables)),
        "sql_only": sorted(set(sql_tables) - set(orm_tables)),
        "swallowed_init_errors": swallowed,
        "ci_migration_guard": guard,
    }
    actx.out[KEY] = output
    actx.rule_inputs["A4"] = {
        "create_all_in_startup": any(item["in_startup"] for item in create_all_sites),
        "revisions": sum(item["revisions"] for item in migration_dirs),
        "upgrade_invocations": len(invocations),
        "swallowed": len(swallowed),
        "sql_tables": len(sql_tables),
        "orm_tables": len(orm_tables),
    }
