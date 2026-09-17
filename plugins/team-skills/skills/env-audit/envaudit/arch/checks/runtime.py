import ast
import getpass
import os
from pathlib import Path
import re
import shlex
import xml.etree.ElementTree as ET

from envaudit.arch import pyast
from envaudit.arch.context import ArchContext, path_inside
from envaudit.arch.checks import tree as tree_check
from envaudit.core.runner import is_git_repo, run as run_command, which


KEY = "runtime"
ORDER = 20

CRONTAB_CMD = ("crontab", "-l")
SYSTEMCTL = "systemctl"
ETC_SYSTEMD_DIR = Path(
    os.environ.get("ENVAUDIT_ETC_SYSTEMD_DIR", "/etc/systemd/system")
)
USER_UNIT_DIRS = tuple(
    value
    for value in os.environ.get(
        "ENVAUDIT_USER_UNIT_DIRS", "~/.config/systemd/user"
    ).split(os.pathsep)
    if value
)


def _text(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def _tokens(command: str) -> list[str]:
    stripped = command.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            value = ast.literal_eval(stripped)
        except (SyntaxError, ValueError):
            value = None
        if isinstance(value, (list, tuple)) and all(
            isinstance(item, str) for item in value
        ):
            return list(value)
        command = stripped[1:-1].replace(",", " ")
    try:
        return shlex.split(command, comments=False, posix=True)
    except ValueError:
        return command.replace("[", " ").replace("]", " ").replace(",", " ").split()


def _command_candidate(
    tokens: list[str], base: Path, home: Path
) -> tuple[Path | None, int | None, bool]:
    python_command = re.compile(r"python(?:\d+(?:\.\d+)?)?", re.I)
    for executable_index, token in enumerate(tokens):
        executable = Path(token.strip("'\";,()[]{}"))
        if python_command.fullmatch(executable.name) is None:
            continue
        for index in range(executable_index + 1, len(tokens) - 1):
            if tokens[index] in {"&&", ";", "|"}:
                break
            if tokens[index] != "-m":
                continue
            module = tokens[index + 1].strip("'\";,()[]{}")
            if not module:
                break
            module_path = Path(*module.split("."))
            choices = [
                base / module_path.with_suffix(".py"),
                base / module_path / "__main__.py",
            ]
            candidate = next(
                (path for path in choices if path.is_file()), choices[-1]
            )
            return candidate, index + 1, True

    for executable_index, token in enumerate(tokens):
        executable = Path(token.strip("'\";,()[]{}"))
        if executable.name.lower() not in {"gunicorn", "uvicorn"}:
            continue
        for index in range(executable_index + 1, len(tokens)):
            clean = tokens[index].strip("'\";,()[]{}")
            module, separator, _ = clean.partition(":")
            if separator and re.fullmatch(
                r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module
            ):
                return (
                    base / Path(*module.split(".")).with_suffix(".py"),
                    index,
                    True,
                )

    for index, token in enumerate(tokens):
        clean = token.strip("'\";,()[]{}")
        if clean.lower().endswith((".py", ".sh", ".php", ".js", ".ts")):
            if clean.startswith("~"):
                clean = str(home) + clean[1:]
            candidate = Path(clean)
            relative = not candidate.is_absolute()
            return (base / candidate if relative else candidate), index, relative
    return None, None, False


def _systemd_value(actx: ArchContext, value: str) -> tuple[str, bool]:
    unresolved = False

    def replace(match: re.Match[str]) -> str:
        nonlocal unresolved
        specifier = match.group(1)
        if specifier == "%":
            return "%"
        if specifier == "h":
            return str(actx.ctx.home)
        if specifier == "u":
            return getpass.getuser()
        unresolved = True
        return match.group(0)

    return re.sub(r"%(.)", replace, value), unresolved


def _real_path(actx: ArchContext, token: str, base: Path) -> Path | None:
    clean = token.strip("'\";,()[]{}")
    if not clean:
        return None
    if clean.startswith("~"):
        clean = str(actx.ctx.home) + clean[1:]
    candidate = Path(clean)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        return Path(os.path.realpath(candidate))
    except OSError:
        return None


def _relative_entry(actx: ArchContext, candidate: Path | None) -> tuple[str | None, str]:
    if candidate is None or not path_inside(candidate, actx.root):
        return None, "unresolved"
    try:
        rel = candidate.relative_to(actx.root).as_posix()
    except ValueError:
        return None, "unresolved"
    return rel, "resolved" if candidate.is_file() else "unresolved"


def _command_facts(
    actx: ArchContext,
    command: str,
    working_directory: str | None = None,
    *,
    systemd: bool = False,
    working_directory_unresolved: bool = False,
) -> tuple[str | None, str, bool, list[Path]]:
    raw_tokens = _tokens(command)
    if systemd:
        expanded = [_systemd_value(actx, token) for token in raw_tokens]
        tokens = [token for token, _ in expanded]
        unresolved_tokens = [unresolved for _, unresolved in expanded]
    else:
        tokens = raw_tokens
        unresolved_tokens = [False for _ in tokens]
    base = actx.ctx.home
    base_unresolved = working_directory_unresolved
    paths: list[Path] = []
    if working_directory and not working_directory_unresolved:
        working = _real_path(actx, working_directory, actx.root)
        if working is not None:
            base = working
            paths.append(working)
    for index, token in enumerate(tokens[:-1]):
        if token != "cd":
            continue
        if unresolved_tokens[index + 1]:
            base_unresolved = True
            continue
        working = _real_path(actx, tokens[index + 1], base)
        if working is not None:
            base = working
            base_unresolved = False
            paths.append(working)
    for token, unresolved in zip(tokens, unresolved_tokens):
        if not unresolved and token.startswith(("/", "~")):
            path = _real_path(actx, token, base)
            if path is not None:
                paths.append(path)

    candidate, candidate_index, relative = _command_candidate(
        tokens, base, actx.ctx.home
    )
    if candidate_index is not None and (
        unresolved_tokens[candidate_index] or (base_unresolved and relative)
    ):
        candidate = None
    if candidate is not None:
        candidate = Path(os.path.realpath(candidate))
        paths.append(candidate)
    entry, state = _relative_entry(actx, candidate)
    intersects = any(path_inside(path, actx.root) for path in paths)
    return entry, state, intersects, paths


def _live_record(
    actx: ArchContext,
    *,
    source: str,
    name: str,
    schedule: str | None,
    command: str,
    working_directory: str | None,
    installed: bool,
    active: bool | None,
    environment_files: list[str] | None = None,
) -> tuple[dict, dict]:
    systemd = source in {"user_unit", "system_unit"}
    effective_working = working_directory
    working_unresolved = False
    if systemd and working_directory:
        effective_working, working_unresolved = _systemd_value(
            actx, working_directory
        )
    entry, state, intersects, paths = _command_facts(
        actx,
        command,
        effective_working,
        systemd=systemd,
        working_directory_unresolved=working_unresolved,
    )
    base = (
        _real_path(actx, effective_working, actx.ctx.home)
        if effective_working and not working_unresolved
        else actx.ctx.home
    )
    for value in environment_files or []:
        clean = value.removeprefix("-")
        unresolved = False
        if systemd:
            clean, unresolved = _systemd_value(actx, clean)
        path = (
            None
            if unresolved
            else _real_path(actx, clean, base or actx.ctx.home)
        )
        if path is not None:
            paths.append(path)
            intersects = intersects or path_inside(path, actx.root)
    return (
        {
            "source": source,
            "name": name,
            "schedule": schedule,
            "entry": entry,
            "entry_parse": state,
            "installed": installed,
            "active": active,
            "closure_has_code": None,
            "intersects_groups": None,
            "intersects_root": intersects,
        },
        {
            "working_directory": effective_working,
            "paths": paths,
            "command": command,
        },
    )


def _crontab(actx: ArchContext) -> tuple[list[dict], list[dict]]:
    executable = which(CRONTAB_CMD[0])
    if executable is None:
        return [], []
    result = run_command([executable, *CRONTAB_CMD[1:]], timeout=20)
    if result.rc != 0:
        return [], []
    records = []
    meta = []
    for number, raw in enumerate(_text(result.stdout).splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("@"):
            continue
        fields = line.split(None, 5)
        if len(fields) != 6:
            continue
        record, details = _live_record(
            actx,
            source="crontab",
            name=f"cron#{number}",
            schedule=" ".join(fields[:5]),
            command=fields[5],
            working_directory=None,
            installed=True,
            active=True,
        )
        records.append(record)
        meta.append(details)
    return records, meta


def _unit_fields(text: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values.setdefault(key.strip(), []).append(value.strip())
    return values


def _systemctl_user(actx: ArchContext) -> tuple[list[dict], list[dict]]:
    executable = which(SYSTEMCTL)
    if executable is None:
        return [], []
    listed = run_command(
        [executable, "--user", "list-timers", "--all", "--no-legend"],
        timeout=20,
    )
    if listed.rc != 0:
        return [], []
    units = []
    for line in _text(listed.stdout).splitlines():
        names = [field for field in line.split() if field.endswith(".timer")]
        if names and names[-1] not in units:
            units.append(names[-1])

    records = []
    meta = []
    for timer in units:
        service = timer.removesuffix(".timer") + ".service"
        documents = []
        for name in (timer, service):
            result = run_command([executable, "--user", "cat", name], timeout=20)
            if result.rc == 0:
                documents.append(_text(result.stdout))
        fields = _unit_fields("\n".join(documents))
        commands = fields.get("ExecStart", [])
        if not commands:
            commands = [""]
        schedule = next(iter(fields.get("OnCalendar", [])), None)
        working = next(iter(fields.get("WorkingDirectory", [])), None)
        for command in commands:
            record, details = _live_record(
                actx,
                source="user_unit",
                name=service,
                schedule=schedule,
                command=command,
                working_directory=working,
                installed=True,
                active=True,
                environment_files=fields.get("EnvironmentFile", []),
            )
            records.append(record)
            meta.append(details)
    return records, meta


def _system_units(actx: ArchContext) -> tuple[list[dict], list[dict]]:
    directory = ETC_SYSTEMD_DIR
    try:
        paths = sorted(directory.glob("*.service"), key=lambda path: path.name)
    except OSError:
        return [], []
    records = []
    meta = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fields = _unit_fields(text)
        working = next(iter(fields.get("WorkingDirectory", [])), None)
        for command in fields.get("ExecStart", []):
            record, details = _live_record(
                actx,
                source="system_unit",
                name=path.name,
                schedule=next(iter(fields.get("OnCalendar", [])), None),
                command=command,
                working_directory=working,
                installed=True,
                active=None,
                environment_files=fields.get("EnvironmentFile", []),
            )
            if record["intersects_root"] or working:
                records.append(record)
                meta.append(details)
    return records, meta


def _read_text(actx: ArchContext, entry) -> str | None:
    data = actx.read(entry)
    return _text(data) if data is not None else None


def _ci(actx: ArchContext) -> tuple[dict, list[tuple[str, str]]]:
    files = []
    texts = []
    deploy = False
    host = False
    for entry in actx.files():
        rel = entry.rel
        if not (
            rel == ".gitlab-ci.yml"
            or rel.startswith(".github/workflows/")
        ):
            continue
        text = _read_text(actx, entry)
        if text is None:
            continue
        files.append(rel)
        texts.append((rel, text))
        deploy = deploy or re.search(r"\b(?:ssh|deploy|rsync|scp)\b", text, re.I) is not None
        host = host or re.search(
            r"(?:\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b|@[A-Za-z0-9.-]+)", text
        ) is not None
    return {
        "files": sorted(files),
        "has_deploy_job": deploy,
        "mentions_host": host,
    }, texts


def _compose_services(text: str) -> tuple[list[dict], set[str]]:
    services = []
    contexts = set()
    in_services = False
    services_indent = 0
    current = None
    current_indent = 0
    build_mapping = False
    for number, raw in enumerate(text.splitlines(), 1):
        clean = raw.split("#", 1)[0].rstrip()
        if not clean:
            continue
        indent = len(clean) - len(clean.lstrip(" "))
        stripped = clean.strip()
        if stripped == "services:":
            in_services = True
            services_indent = indent
            continue
        if not in_services:
            continue
        if indent <= services_indent:
            break
        match = re.match(r"([A-Za-z0-9_.-]+):\s*$", stripped)
        if match and indent == services_indent + 2:
            if current:
                services.append(current)
            current = {
                "name": match.group(1),
                "line": number,
                "command": None,
                "build": None,
                "dockerfile": None,
                "image": None,
            }
            current_indent = indent
            build_mapping = False
            continue
        if current is None or indent <= current_indent:
            continue
        command = re.match(r"command:\s*(.+)$", stripped)
        if command:
            current["command"] = command.group(1).strip()
            current["line"] = number
            continue
        build = re.match(r"build:\s*(.*)$", stripped)
        if build:
            value = build.group(1).strip()
            build_mapping = not bool(value)
            if not value:
                current["build"] = "."
                contexts.add(".")
            else:
                if value.startswith("{") and value.endswith("}"):
                    fields = {}
                    for item in value[1:-1].split(","):
                        key, separator, field_value = item.partition(":")
                        if separator:
                            fields[key.strip()] = field_value.strip().strip("'\"")
                    current["build"] = fields.get("context", ".")
                    current["dockerfile"] = fields.get("dockerfile")
                else:
                    current["build"] = value.strip("'\"")
                contexts.add(current["build"])
            continue
        if build_mapping:
            context = re.match(r"context:\s*(.+)$", stripped)
            if context:
                current["build"] = context.group(1).strip("'\"")
                contexts.add(current["build"])
                continue
            dockerfile = re.match(r"dockerfile:\s*(.+)$", stripped)
            if dockerfile:
                current["dockerfile"] = dockerfile.group(1).strip("'\"")
                continue
        image = re.match(r"image:\s*(.+)$", stripped)
        if image:
            current["image"] = image.group(1).strip("'\"")
    if current:
        services.append(current)
    return services, contexts


def _subprojects(
    actx: ArchContext, ci_texts: list[tuple[str, str]]
) -> tuple[list[str], set[str]]:
    candidates = set()
    root_contexts = set()
    root_container_texts = []
    has_root_container = False
    for entry in actx.files():
        path = Path(entry.rel)
        lower = path.name.lower()
        if lower.startswith("docker-compose") and lower.endswith((".yml", ".yaml")):
            if path.parent != Path("."):
                candidates.add(path.parent.as_posix())
            else:
                has_root_container = True
                text = _read_text(actx, entry)
                if text:
                    root_container_texts.append(text)
                    _, contexts = _compose_services(text)
                    for context in contexts:
                        normalized = Path(context.removeprefix("./")).as_posix()
                        root_contexts.add(normalized)
        elif path.name.startswith("Dockerfile"):
            if path.parent != Path("."):
                candidates.add(path.parent.as_posix())
            else:
                has_root_container = True
                text = _read_text(actx, entry)
                if text:
                    root_container_texts.append(text)

    if not has_root_container:
        return [], candidates

    included = set()
    references = "\n".join(
        [*root_container_texts, *(text for _, text in ci_texts)]
    )
    for candidate in candidates:
        if any(
            context == candidate
            or context.startswith(candidate + "/")
            or candidate.startswith(context + "/")
            for context in root_contexts
        ) or candidate in references:
            included.add(candidate)
    return sorted(candidates - included), included


def _under(rel: str, directories: list[str]) -> bool:
    return any(rel == directory or rel.startswith(directory + "/") for directory in directories)


def _entry_from_command(actx: ArchContext, command: str, base: Path) -> str | None:
    tokens = _tokens(command)
    candidate, _, _ = _command_candidate(tokens, base, actx.ctx.home)
    if candidate is None:
        return None
    candidate = Path(os.path.abspath(candidate))
    try:
        return candidate.relative_to(actx.trees["primary"].path).as_posix()
    except ValueError:
        return None


def _server_app_from_command(
    actx: ArchContext, command: str, base: Path
) -> tuple[str, str] | None:
    parts = _tokens(command)
    server_index = next(
        (
            index
            for index, part in enumerate(parts)
            if Path(part.strip("'\";,()[]{}")).name.lower()
            in {"gunicorn", "uvicorn"}
        ),
        None,
    )
    if server_index is None:
        return None
    for part in parts[server_index + 1 :]:
        clean = part.strip("'\";,()[]{}")
        match = re.fullmatch(
            r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w)*):([A-Za-z_]\w*)", clean
        )
        if match is None:
            continue
        module, object_name = match.groups()
        module_path = Path(*module.split("."))
        choices = [
            base / module_path.with_suffix(".py"),
            base / module_path / "__init__.py",
        ]
        candidate = next((path for path in choices if path.is_file()), choices[0])
        try:
            rel = candidate.relative_to(actx.trees["primary"].path).as_posix()
        except ValueError:
            return None
        return rel, object_name
    return None


def _python_call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _python_call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _assigned_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [
            name
            for item in node.elts
            for name in _assigned_names(item)
        ]
    return []


def _python_web_line(
    parsed: ast.Module, module_objects: set[str]
) -> int | None:
    framework_objects: set[str] = set()
    exported_objects: dict[str, int] = {}
    calls: list[tuple[str, int]] = []
    constructors: list[tuple[str, int]] = []

    for node in ast.walk(parsed):
        if isinstance(node, ast.Call):
            name = _python_call_name(node.func)
            if name is not None:
                calls.append((name, node.lineno))
                terminal = name.rsplit(".", 1)[-1]
                if terminal in {"Dispatcher", "Bot"}:
                    constructors.append((terminal, node.lineno))
        value = None
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            value = node.value
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            value = node.value
            targets = [node.target]
        if not isinstance(value, ast.Call):
            continue
        constructor = _python_call_name(value.func)
        if constructor is None:
            continue
        terminal = constructor.rsplit(".", 1)[-1]
        names = [name for target in targets for name in _assigned_names(target)]
        if terminal in {"Flask", "FastAPI"}:
            framework_objects.update(names)
        if terminal == "FastAPI" or constructor == "web.Application":
            for name in names:
                exported_objects[name] = value.lineno

    launch_lines = [
        line
        for name, line in calls
        if name in {"web.run_app", "uvicorn.run"}
        or name.rsplit(".", 1)[-1] == "serve_forever"
    ]
    launch_lines.extend(
        line
        for name, line in calls
        if name.rsplit(".", 1)[-1] == "run"
        and name.rpartition(".")[0] in framework_objects
    )
    polling_lines = [
        line
        for name, line in calls
        if name.rsplit(".", 1)[-1] in {"start_polling", "run_polling"}
    ]
    if polling_lines and constructors:
        launch_lines.extend(polling_lines)
    launch_lines.extend(
        line
        for name, line in exported_objects.items()
        if name in module_objects
    )
    return min(launch_lines) if launch_lines else None


def _repo_anchors(
    actx: ArchContext, subprojects: list[str]
) -> tuple[list[dict], list[dict]]:
    anchors = []
    meta = []
    python_seen: dict[str, ast.Module] = {}
    settings_dirs: set[str] = set()
    server_apps: dict[str, set[str]] = {}

    for entry in actx.files():
        if _under(entry.rel, subprojects):
            continue
        path = Path(entry.rel)
        name = path.name
        lower = name.lower()
        text = None

        if name.startswith("Dockerfile"):
            text = _read_text(actx, entry)
            if text is not None:
                lines = text.splitlines()
                start = max(
                    (index for index, line in enumerate(lines) if line.lstrip().upper().startswith("FROM ")),
                    default=0,
                )
                command_line = None
                command_number = None
                for index, line in enumerate(lines[start:], start + 1):
                    if re.match(r"\s*(?:CMD|ENTRYPOINT)\b", line, re.I):
                        command_line = re.sub(r"^\s*(?:CMD|ENTRYPOINT)\s*", "", line, flags=re.I)
                        command_number = index
                if command_line is not None:
                    base = actx.trees["primary"].path / path.parent
                    build_context = path.parent.as_posix()
                    server_app = _server_app_from_command(
                        actx, command_line, base
                    )
                    if server_app is not None:
                        server_apps.setdefault(server_app[0], set()).add(
                            server_app[1]
                        )
                    anchors.append(
                        {
                            "kind": "dockerfile_cmd",
                            "file": entry.rel,
                            "line": command_number,
                            "entry": _entry_from_command(actx, command_line, base),
                            "image_group": [build_context, entry.rel],
                            "schedule": None,
                            "live": False,
                        }
                    )
                    meta.append({"build_context": build_context})
            continue

        if lower.startswith("docker-compose") and lower.endswith((".yml", ".yaml")):
            text = _read_text(actx, entry)
            if text is not None:
                services, _ = _compose_services(text)
                for service in services:
                    if not service["command"] and not service["build"]:
                        continue
                    context = service["build"] or service["image"] or service["name"]
                    context = Path(path.parent, str(context).removeprefix("./")).as_posix()
                    if service["build"]:
                        dockerfile = Path(
                            context, service["dockerfile"] or "Dockerfile"
                        ).as_posix()
                        image_group = [context, dockerfile]
                    else:
                        image_group = context
                    base = actx.trees["primary"].path / path.parent
                    server_app = _server_app_from_command(
                        actx, service["command"] or "", base
                    )
                    if server_app is not None:
                        server_apps.setdefault(server_app[0], set()).add(
                            server_app[1]
                        )
                    anchors.append(
                        {
                            "kind": "compose_services",
                            "file": entry.rel,
                            "line": service["line"],
                            "entry": _entry_from_command(
                                actx, service["command"] or "", base
                            ),
                            "image_group": image_group,
                            "schedule": None,
                            "live": False,
                        }
                    )
                    meta.append({"build_context": context})
            continue

        if entry.rel.startswith("deploy/") and lower.endswith((".service", ".timer")):
            text = _read_text(actx, entry)
            fields = _unit_fields(text or "")
            command = next(iter(fields.get("ExecStart", [])), "")
            working = next(iter(fields.get("WorkingDirectory", [])), None)
            working_unresolved = False
            if working:
                working, working_unresolved = _systemd_value(actx, working)
            parsed_entry, _, _, _ = _command_facts(
                actx,
                command,
                working,
                systemd=True,
                working_directory_unresolved=working_unresolved,
            )
            anchors.append(
                {
                    "kind": "repo_unit",
                    "file": entry.rel,
                    "line": 1,
                    "entry": parsed_entry,
                    "image_group": None,
                    "schedule": next(iter(fields.get("OnCalendar", [])), None),
                    "live": False,
                }
            )
            meta.append({})
            continue

        if path.suffix.lower() == ".py":
            if not actx.is_prod_path(entry.rel):
                continue
            data = actx.read(entry)
            if data is not None:
                parsed = pyast.parse(data, entry.rel)
                if parsed is not None:
                    python_seen[entry.rel] = parsed
            if name == "settings.py" and data and b"INSTALLED_APPS" in data:
                settings_dirs.add(path.parent.as_posix())
            continue

        if path.suffix.lower() == ".php":
            if not actx.is_prod_path(entry.rel):
                continue
            text = _read_text(actx, entry)
            if text is None:
                continue
            plugin = (
                re.search(r"(?:^|/)local/modules/[^/]+/install/index\.php$", entry.rel) is not None
                or (name == "install.php" and re.search(r"RegisterModuleDependences|registerEventHandler|OnProlog", text, re.I) is not None)
                or (re.search(r"(?:^|/)local/tools/[^/]+/[^/]+\.php$", entry.rel) is not None and re.search(r"\$_(?:POST|REQUEST)", text) is not None)
            )
            if plugin:
                anchors.append(
                    {
                        "kind": "php_host_plugin",
                        "file": entry.rel,
                        "line": 1,
                        "entry": entry.rel,
                        "image_group": None,
                        "schedule": None,
                        "live": False,
                    }
                )
                meta.append({})
            continue

        if path.suffix.lower() == ".csproj":
            if not actx.is_prod_path(entry.rel):
                continue
            data = actx.read(entry)
            if data is None:
                continue
            try:
                root = ET.fromstring(data)
            except ET.ParseError:
                continue
            values = {element.tag.rsplit("}", 1)[-1]: (element.text or "").strip() for element in root.iter()}
            test_project = any(
                element.tag.rsplit("}", 1)[-1] == "PackageReference"
                and element.attrib.get("Include", "").lower()
                == "microsoft.net.test.sdk"
                for element in root.iter()
            )
            if test_project:
                continue
            if values.get("OutputType", "").lower() == "winexe" or values.get("UseWPF", "").lower() == "true":
                anchors.append(
                    {
                        "kind": "desktop",
                        "file": entry.rel,
                        "line": 1,
                        "entry": entry.rel,
                        "image_group": None,
                        "schedule": None,
                        "live": False,
                    }
                )
                meta.append({})

    for rel, parsed in sorted(python_seen.items()):
        path = Path(rel)
        django_entry = (
            path.name == "manage.py" and path.parent.as_posix() in settings_dirs
        )
        line = 1 if django_entry else _python_web_line(
            parsed, server_apps.get(rel, set())
        )
        if line is not None:
            anchors.append(
                {
                    "kind": "web_app",
                    "file": rel,
                    "line": line,
                    "entry": rel,
                    "image_group": None,
                    "schedule": None,
                    "live": False,
                }
            )
            meta.append({})
    return anchors, meta


def _live_anchors(units: list[dict]) -> list[dict]:
    anchors = []
    for unit in units:
        if not unit.get("intersects_root"):
            continue
        kind = "cron_entries" if unit["source"] == "crontab" else "systemd_units"
        anchors.append(
            {
                "kind": kind,
                "file": None,
                "line": None,
                "entry": unit.get("entry"),
                "image_group": None,
                "schedule": unit.get("schedule"),
                "live": True,
            }
        )
    return anchors


def _deploy_dirs(
    actx: ArchContext,
    units: list[dict],
    meta: list[dict],
    repo_unit_names: set[str],
) -> list[dict]:
    output = {}
    for unit, details in zip(units, meta):
        working = details.get("working_directory")
        if not isinstance(working, str):
            continue
        path = _real_path(actx, working, actx.root)
        if path is None or path_inside(path, actx.root):
            continue
        output[str(path)] = {
            "path": str(path),
            "matched_repo_unit": unit.get("name") in repo_unit_names,
            "is_git_checkout": is_git_repo(path) if path.is_dir() else False,
            "files_compared": None,
            "files_drift": None,
            "lines_drift": None,
            "drift_matches_commit": None,
        }
    return [output[key] for key in sorted(output)]


def _docker_working_dirs(actx: ArchContext) -> list[str] | None:
    executable = which("docker")
    if executable is None:
        actx.skip(KEY, "not_applicable", "docker")
        return None
    listed = run_command([executable, "ps", "--format", "{{.ID}}"], timeout=20)
    if listed.rc != 0:
        actx.skip(KEY, "not_applicable", "docker")
        return None
    paths = set()
    for container_id in listed.stdout.splitlines():
        if not container_id:
            continue
        inspected = run_command(
            [
                executable,
                "inspect",
                "--format",
                '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}',
                container_id.decode("ascii", "ignore"),
            ],
            timeout=20,
        )
        if inspected.rc != 0:
            continue
        value = _text(inspected.stdout).strip()
        if value and value != "<no value>":
            paths.add(str(Path(os.path.realpath(Path(value).expanduser()))))
    return sorted(paths)


def run(actx: ArchContext) -> None:
    units = []
    unit_meta = []
    for collector in (_crontab, _systemctl_user, _system_units):
        records, meta = collector(actx)
        units.extend(records)
        unit_meta.extend(meta)

    actx.out[KEY] = {
        "anchors": [],
        "live_units": units,
        "ci": {"files": [], "has_deploy_job": False, "mentions_host": False},
        "deploy_dirs": [],
        "docker_working_dirs": None,
        "manual_gate_doc": None,
    }
    tree_check.finalize_tree(actx)

    ci, ci_texts = _ci(actx)
    subprojects, _ = _subprojects(actx, ci_texts)
    repo_anchors, anchor_meta = _repo_anchors(actx, subprojects)
    live_anchors = _live_anchors(units)
    anchors = live_anchors + repo_anchors
    meta = [{} for _ in live_anchors] + anchor_meta
    repo_unit_names = {
        Path(anchor["file"]).name
        for anchor in repo_anchors
        if anchor["kind"] == "repo_unit" and anchor.get("file")
    }
    actx.out[KEY].update(
        {
            "anchors": anchors,
            "ci": ci,
            "deploy_dirs": _deploy_dirs(
                actx, units, unit_meta, repo_unit_names
            ),
            "docker_working_dirs": (
                _docker_working_dirs(actx) if actx.ctx.flags.docker else None
            ),
        }
    )
    actx.cache["runtime_anchor_meta"] = meta
    actx.cache["subprojects"] = subprojects
    if not actx.ctx.flags.docker:
        actx.skip(KEY, "flag_off", "docker")
    tree_check.refresh_source_roots(actx)
