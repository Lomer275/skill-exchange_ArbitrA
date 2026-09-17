import ast
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import time

from envaudit.arch import pyast
from envaudit.arch.closure import import_closure
from envaudit.arch.context import ArchContext, path_inside
from envaudit.arch.checks import runtime
from envaudit.core.runner import git, git_stream


KEY = "ops"
ORDER = 60
CODE_EXTENSIONS = frozenset(
    {".py", ".php", ".js", ".jsx", ".ts", ".tsx", ".cs", ".sh"}
)
DESTRUCTIVE_CALL = re.compile(
    rb"disk\.file\.delete|\.delete\b|crm\.\w+\.delete|markdeleted",
    re.I,
)
DEFAULT_REFUSAL = re.compile(
    r"(?i)(lock.{0,40}(busy|held|refus|skip|another|already)|"
    r"already running|no-op|is running)"
)
DEFAULT_SUCCESS = re.compile(
    r"(?i)(\b\w+_seen=|\bprocessed=|\bsent=|\bdone\b|\bfinished\b|\bcompleted\b)"
)
HINT_DIR = re.compile(r"(?i)^(?:99_|дубл|archive|old|copy)")
SKIP_BASENAMES = frozenset(
    {".env", "users", "users.txt", "userlist", "userlist.txt", "shadow"}
)


def _line_count(data: bytes) -> int:
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def _relevant_units(actx: ArchContext) -> list[dict] | None:
    units = actx.live_units()
    if units is None:
        return None
    return [
        unit
        for unit in units
        if isinstance(unit, dict) and unit.get("intersects_root") is True
    ]


def _git_number(actx: ArchContext, *args: str) -> int:
    result = git(actx.root, *args, timeout=180)
    if result.rc != 0:
        return 0
    try:
        return int(result.stdout.strip() or b"0")
    except ValueError:
        return 0


def _numstat(actx: ArchContext, paths: list[str]) -> tuple[int, int]:
    if not paths:
        return 0, 0
    result = git(
        actx.root,
        "diff",
        "--no-textconv",
        "--no-ext-diff",
        "--numstat",
        "--ignore-cr-at-eol",
        "HEAD",
        "--",
        *paths,
        timeout=180,
    )
    if result.rc != 0:
        return 0, 0
    added = 0
    deleted = 0
    for line in result.stdout.splitlines():
        fields = line.split(b"\t", 2)
        if len(fields) != 3:
            continue
        try:
            added += int(fields[0]) if fields[0] != b"-" else 0
            deleted += int(fields[1]) if fields[1] != b"-" else 0
        except ValueError:
            continue
    return added, deleted


def _outside_counts(
    actx: ArchContext, closure: set[str], entries: dict[str, object]
) -> tuple[int, int]:
    outside = 0
    ignored = 0
    for rel in sorted(closure):
        history = git(
            actx.root,
            "log",
            "--all",
            "--format=%H",
            "-1",
            "--",
            rel,
        )
        tracked = git(actx.root, "ls-files", "--error-unmatch", "--", rel)
        if history.rc == 0 and history.stdout.strip() or tracked.rc == 0:
            continue
        entry = entries.get(rel)
        data = actx.read(entry) if entry is not None else None
        lines = _line_count(data or b"")
        check = git(actx.root, "check-ignore", "--no-index", "--quiet", "--", rel)
        if check.rc == 0:
            ignored += lines
        else:
            outside += lines
    return outside, ignored


def _a1(actx: ArchContext, output: dict) -> None:
    units = _relevant_units(actx)
    if units is None or any(unit.get("entry_parse") != "resolved" for unit in units):
        actx.rule_inputs["A1"] = {"measured": False}
        return
    entries = {entry.rel: entry for entry in actx.files("worktree")}
    tree = actx.out.get("tree", {})
    verified = bool(isinstance(tree, dict) and tree.get("ahead_verified") is True)
    combined_closure = set()
    for unit in units:
        entry = unit.get("entry")
        if not isinstance(entry, str):
            actx.rule_inputs["A1"] = {"measured": False}
            return
        closure = import_closure(actx, entry, "worktree")
        combined_closure.update(closure)
        unit["closure_has_code"] = bool(closure)
        outside, ignored = _outside_counts(actx, closure, entries)
        added, deleted = _numstat(actx, sorted(closure))
        ahead = (
            _git_number(
                actx,
                "rev-list",
                "--count",
                "HEAD",
                "--not",
                "--remotes",
                "--",
                *sorted(closure),
            )
            if closure
            else 0
        )
        output["live_closure"].append(
            {
                "unit": unit.get("name", ""),
                "entry": entry,
                "modules": len(closure),
                "outside_git_lines": outside,
                "ignored_lines": ignored,
                "uncommitted_add": added,
                "uncommitted_del": deleted,
                "ahead_closure": ahead,
                "ahead_verified": verified,
            }
        )
    outside, ignored = _outside_counts(actx, combined_closure, entries)
    added, deleted = _numstat(actx, sorted(combined_closure))
    ahead = (
        _git_number(
            actx,
            "rev-list",
            "--count",
            "HEAD",
            "--not",
            "--remotes",
            "--",
            *sorted(combined_closure),
        )
        if combined_closure
        else 0
    )
    ci = actx.out.get("runtime", {}).get("ci", {})
    actx.rule_inputs["A1"] = {
        "live_units": len(units),
        "outside_git_lines": outside,
        "ignored_lines": ignored,
        "uncommitted_lines": added + deleted,
        "ahead_closure": ahead,
        "entry_parse": "resolved",
        "tree_id": "worktree",
        "ci_mentions_host": bool(
            isinstance(ci, dict) and ci.get("mentions_host") is True
        ),
    }


def _runtime_pairs(actx: ArchContext) -> list[tuple[dict, dict]]:
    cached = actx.cache.get("ops_runtime_pairs")
    if isinstance(cached, list):
        return cached
    pairs = []
    for collector in (runtime._crontab, runtime._systemctl_user, runtime._system_units):
        records, details = collector(actx)
        pairs.extend(zip(records, details))
    actx.cache["ops_runtime_pairs"] = pairs
    return pairs


def _command_module(command: str) -> str | None:
    parts = runtime._tokens(command)
    for index, part in enumerate(parts[:-1]):
        if part == "-m":
            return parts[index + 1].strip("'\";,()[]{}")
    return None


def _repo_units(actx: ArchContext) -> dict[str, set[str]]:
    result = {}
    for entry in actx.files("worktree"):
        if not entry.rel.endswith(".service"):
            continue
        data = actx.read(entry)
        if data is None:
            continue
        fields = runtime._unit_fields(data.decode("utf-8", "replace"))
        modules = {
            module
            for command in fields.get("ExecStart", [])
            if (module := _command_module(command)) is not None
        }
        result.setdefault(Path(entry.rel).name, set()).update(modules)
    return result


def _blob_map(actx: ArchContext) -> set[str]:
    cached = actx.cache.get("ops_blob_map")
    if isinstance(cached, set):
        return cached
    result = set()
    for raw in git_stream(
        actx.root,
        "log",
        "--all",
        "--raw",
        "--no-abbrev",
        "--format=%x00%H",
        timeout=600,
    ):
        line = raw.strip()
        if not line.startswith(b":"):
            continue
        fields = line.split(None, 5)
        if len(fields) >= 4:
            for value in fields[2:4]:
                if re.fullmatch(rb"[0-9a-f]{40,64}", value) and set(value) != {48}:
                    result.add(value.decode("ascii"))
    actx.cache["ops_blob_map"] = result
    return result


def _blob_sha(data: bytes) -> str:
    prefix = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(prefix + data).hexdigest()


def _diff_lines(old: bytes, new: bytes) -> int:
    before = old.decode("utf-8", "replace").splitlines()
    after = new.decode("utf-8", "replace").splitlines()
    total = 0
    for kind, left_a, left_b, right_a, right_b in difflib.SequenceMatcher(
        None, before, after, autojunk=False
    ).get_opcodes():
        if kind != "equal":
            total += max(left_b - left_a, right_b - right_a)
    return total


def _safe_deploy_file(path: Path) -> bool:
    lower = path.name.lower()
    if (
        lower in SKIP_BASENAMES
        or lower.startswith(".env")
        or lower.startswith("config.env")
        or lower.endswith(".env")
        or ".env.bak" in lower
        or path.suffix.lower() in {".pem", ".key"}
        or path.stem.lower() in {"users", "userlist", "user_list", "user-list"}
    ):
        return False
    if any(word in lower for word in ("credential", "passwd", "private_key")):
        return False
    return True


def _compare_deploy_dir(actx: ArchContext, item: dict) -> None:
    root = Path(item["path"])
    history_blobs = _blob_map(actx)
    compared = 0
    drift = 0
    lines = 0
    matches = []
    try:
        walker = os.walk(root, followlinks=False)
        for current, dirs, names in walker:
            dirs[:] = [
                name
                for name in dirs
                if name not in {".git", ".venv", "venv", "node_modules"}
            ]
            for name in names:
                path = Path(current) / name
                if not _safe_deploy_file(path) or path.is_symlink():
                    continue
                try:
                    rel = path.relative_to(root).as_posix()
                    deployed = path.read_bytes()
                except OSError:
                    continue
                head = git(actx.root, "show", f"HEAD:{rel}", timeout=60)
                if head.rc != 0:
                    continue
                compared += 1
                if deployed == head.stdout:
                    continue
                drift += 1
                lines += _diff_lines(head.stdout, deployed)
                matches.append(_blob_sha(deployed) in history_blobs)
    except OSError:
        pass
    item.update(
        {
            "files_compared": compared,
            "files_drift": drift,
            "lines_drift": lines,
            "drift_matches_commit": all(matches) if matches else True,
        }
    )


def _a2(actx: ArchContext) -> None:
    tree = actx.out.get("tree", {})
    branches = []
    if isinstance(tree, dict):
        for item in [*tree.get("local_branches", []), *tree.get("worktrees", [])]:
            if (
                isinstance(item, dict)
                and item.get("local_only") is True
                and item.get("merged") is not True
                and isinstance(item.get("delta_pct_vs_default"), (int, float))
                and item["delta_pct_vs_default"] > 20
            ):
                branches.append(dict(item))
    runtime_out = actx.out.get("runtime", {})
    deploy_dirs = runtime_out.get("deploy_dirs", []) if isinstance(runtime_out, dict) else []
    deploy_dirs = deploy_dirs if isinstance(deploy_dirs, list) else []
    repo_units = _repo_units(actx)
    pairs = _runtime_pairs(actx)
    matched_deploy_dirs = []
    for item in deploy_dirs:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        live_modules = set()
        live_names = set()
        for unit, details in pairs:
            working = details.get("working_directory")
            resolved = (
                runtime._real_path(actx, working, actx.root)
                if isinstance(working, str)
                else None
            )
            if resolved is None or str(resolved) != item["path"]:
                continue
            live_names.add(unit.get("name"))
            module = _command_module(str(details.get("command", "")))
            if module:
                live_modules.add(module)
        item["matched_repo_unit"] = bool(
            item.get("matched_repo_unit") is True
            or live_names.intersection(repo_units)
            or any(live_modules.intersection(values) for values in repo_units.values())
        )
        if item["matched_repo_unit"]:
            _compare_deploy_dir(actx, item)
            matched_deploy_dirs.append(item)
    if isinstance(runtime_out, dict):
        runtime_out["deploy_dirs"] = matched_deploy_dirs
    actx.rule_inputs["A2"] = {
        "branches": branches,
        "deploy_dirs": matched_deploy_dirs,
        "deploy_dirs_unmatched_count": len(deploy_dirs) - len(matched_deploy_dirs),
    }


def _lock_candidates(
    parsed: ast.Module, wrapper_names: set[str]
) -> list[tuple[str, ast.AST, int]]:
    candidates = []
    for node in parsed.body:
        targets = []
        value = None
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        if value is None:
            continue
        dump = ast.dump(value, include_attributes=False)
        lockish = (
            any("LOCK" in name.upper() for name in targets) or ".lock" in dump.lower()
        )
        candidates.extend(
            (name, value, node.lineno)
            for name in targets
            if lockish or name in wrapper_names
        )
    return candidates


def _feeds_open(parsed: ast.Module, name: str) -> bool:
    for node in ast.walk(parsed):
        if not isinstance(node, ast.Call):
            continue
        call = runtime._python_call_name(node.func)
        if call in {"open", "os.open"} and node.args:
            source = node.args[0]
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "open"
            and isinstance(node.func.value, ast.Name)
        ):
            source = node.func.value
        else:
            continue
        if isinstance(source, ast.Name) and source.id == name:
            return True
        function = next(
            (
                item
                for item in parsed.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node in ast.walk(item)
            ),
            None,
        )
        if function is None or not isinstance(source, ast.Name):
            continue
        positional = [*function.args.posonlyargs, *function.args.args]
        defaults = [None] * (len(positional) - len(function.args.defaults)) + list(
            function.args.defaults
        )
        for argument, default in zip(positional, defaults):
            if (
                argument.arg == source.id
                and isinstance(default, ast.Name)
                and default.id == name
            ):
                return True
    return False


def _bound_names(node: ast.AST | None) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return set().union(*(_bound_names(item) for item in node.elts))
    return set()


def _opened_parameter(call: ast.Call, parameters: set[str]) -> str | None:
    name = runtime._python_call_name(call.func)
    if name in {"open", "os.open"} and call.args:
        source = call.args[0]
    elif isinstance(call.func, ast.Attribute) and call.func.attr == "open":
        source = call.func.value
    else:
        return None
    if isinstance(source, ast.Name) and source.id in parameters:
        return source.id
    return None


def _lock_argument_uses(
    node: ast.AST, parameter: str, handles: dict[str, set[str]]
) -> bool:
    if isinstance(node, ast.Call) and _opened_parameter(node, {parameter}):
        return True
    if isinstance(node, ast.Name):
        return node.id in handles[parameter]
    return bool(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "fileno"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in handles[parameter]
    )


def _function_lock_parameters(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    positional = [*function.args.posonlyargs, *function.args.args]
    parameters = {
        argument.arg for argument in [*positional, *function.args.kwonlyargs]
    }
    handles = {parameter: set() for parameter in parameters}
    for node in ast.walk(function):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if not isinstance(item.context_expr, ast.Call):
                    continue
                parameter = _opened_parameter(item.context_expr, parameters)
                if parameter is not None:
                    handles[parameter].update(_bound_names(item.optional_vars))
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            parameter = _opened_parameter(node.value, parameters)
            if parameter is not None:
                for target in node.targets:
                    handles[parameter].update(_bound_names(target))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Call):
            parameter = _opened_parameter(node.value, parameters)
            if parameter is not None:
                handles[parameter].update(_bound_names(node.target))

    result = set()
    for call in ast.walk(function):
        if not isinstance(call, ast.Call) or not call.args:
            continue
        if runtime._python_call_name(call.func) not in {
            "fcntl.flock",
            "fcntl.lockf",
            "flock",
            "lockf",
        }:
            continue
        if not any(
            isinstance(node, ast.Attribute) and node.attr == "LOCK_NB"
            or isinstance(node, ast.Name) and node.id == "LOCK_NB"
            for node in ast.walk(call)
        ):
            continue
        result.update(
            parameter
            for parameter in parameters
            if _lock_argument_uses(call.args[0], parameter, handles)
        )
    return result


def _wrapper_lock_names(parsed: ast.Module) -> set[str]:
    wrappers = {}
    for node in parsed.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        parameters = _function_lock_parameters(node)
        if parameters:
            wrappers[node.name] = (node, parameters)

    result = set()
    for call in ast.walk(parsed):
        if not isinstance(call, ast.Call):
            continue
        wrapper = wrappers.get(runtime._python_call_name(call.func))
        if wrapper is None:
            continue
        function, lock_parameters = wrapper
        positional = [*function.args.posonlyargs, *function.args.args]
        for parameter in lock_parameters:
            argument = next(
                (
                    keyword.value
                    for keyword in call.keywords
                    if keyword.arg == parameter
                ),
                None,
            )
            if argument is None:
                index = next(
                    (
                        index
                        for index, item in enumerate(positional)
                        if item.arg == parameter
                    ),
                    None,
                )
                if index is not None and index < len(call.args):
                    argument = call.args[index]
            if isinstance(argument, ast.Name):
                result.add(argument.id)
    return result


def _cron_args(command: str, entry: str) -> bytes:
    parts = runtime._tokens(command)
    start = None
    for index, part in enumerate(parts):
        if part == "-m" and index + 1 < len(parts):
            start = index + 2
            break
        clean = part.strip("'\";,()[]{}")
        if clean.endswith(entry) or Path(clean).name == Path(entry).name:
            start = index + 1
            break
    values = [] if start is None else parts[start:]
    for index, value in enumerate(values):
        if value in {">", ">>", "1>", "1>>", "2>", "2>>"} or value.startswith(
            (">", "1>", "2>")
        ):
            values = values[:index]
            break
    return hashlib.sha1("\0".join(values).encode("utf-8", "surrogateescape")).digest()


def _configured_pattern(
    actx: ArchContext, key: str, default: re.Pattern[str]
) -> re.Pattern[str]:
    path = actx.root / ".audit" / "patterns.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        value = document.get(key)
        if isinstance(value, str):
            return re.compile(value, re.I)
    except (OSError, ValueError, re.error):
        pass
    return default


def _redirected_logs(actx: ArchContext, command: str) -> set[Path]:
    base = actx.root
    parts = runtime._tokens(command)
    for index, part in enumerate(parts[:-1]):
        if part == "cd":
            candidate = Path(parts[index + 1]).expanduser()
            if not candidate.is_absolute():
                candidate = base / candidate
            base = candidate
    result = set()
    for match in re.finditer(r">>\s*(?:\"([^\"]+)\"|'([^']+)'|(\S+))", command):
        value = next(group for group in match.groups() if group is not None)
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        candidate = Path(os.path.abspath(candidate))
        if path_inside(candidate, actx.root):
            result.add(candidate)
    return result


def _log_metrics(actx: ArchContext, commands: list[str]) -> list[dict]:
    paths = {
        entry.path
        for entry in actx.files("worktree")
        if entry.rel.endswith(".log")
        and (len(Path(entry.rel).parts) == 1 or Path(entry.rel).parent == Path("logs"))
    }
    for command in commands:
        paths.update(_redirected_logs(actx, command))
    refusal_pattern = _configured_pattern(actx, "lock_refusal", DEFAULT_REFUSAL)
    success_pattern = _configured_pattern(actx, "run_success", DEFAULT_SUCCESS)
    output = []
    for path in sorted(paths, key=str):
        try:
            size = path.stat().st_size
            with path.open("rb") as stream:
                stream.seek(max(0, size - 50 * 1024 * 1024))
                if size > 50 * 1024 * 1024:
                    stream.readline()
                text = stream.read().decode("utf-8", "replace")
        except OSError:
            continue
        refusals = 0
        successes = 0
        for line in text.splitlines():
            if refusal_pattern.search(line):
                refusals += 1
            if success_pattern.search(line):
                successes += 1
        runs = refusals + successes
        try:
            rel = path.relative_to(actx.root).as_posix()
        except ValueError:
            continue
        output.append(
            {
                "log": rel,
                "mode": path.stem.rsplit("-", 1)[-1],
                "runs": runs,
                "refusals": refusals,
                "successes": successes,
                "share": round(refusals / runs, 4) if runs else None,
                "heuristic": True,
            }
        )
    return output


def _a3(actx: ArchContext, output: dict) -> None:
    cron_pairs = [
        (unit, details)
        for unit, details in _runtime_pairs(actx)
        if unit.get("source") == "crontab" and unit.get("intersects_root") is True
    ]
    locks = []
    for entry in actx.code_files("worktree", exts=frozenset({".py"})):
        data = actx.read(entry)
        parsed = pyast.parse(data, entry.rel) if data is not None else None
        if parsed is None:
            continue
        calls = pyast.calls_named(parsed, {"fcntl.flock", "fcntl.lockf", "flock", "lockf"})
        has_nonblocking = any(
            isinstance(node, ast.Attribute) and node.attr == "LOCK_NB"
            or isinstance(node, ast.Name) and node.id == "LOCK_NB"
            for node in ast.walk(parsed)
        )
        if not calls or not has_nonblocking:
            continue
        wrapper_names = _wrapper_lock_names(parsed)
        related = [
            (unit, details)
            for unit, details in cron_pairs
            if unit.get("entry") == entry.rel
        ]
        if len(related) < 2:
            continue
        for name, value, line in _lock_candidates(parsed, wrapper_names):
            if name not in wrapper_names and not _feeds_open(parsed, name):
                continue
            fingerprints = {
                _cron_args(str(details.get("command", "")), entry.rel)
                for _, details in related
            }
            if len(fingerprints) < 2:
                continue
            locks.append(
                {
                    "sort": (entry.rel, line, ast.dump(value, include_attributes=False)),
                    "defined_at": f"{entry.rel}:{line}",
                    "cron_entries": sorted(str(unit.get("name", "")) for unit, _ in related),
                    "distinct_args": len(fingerprints),
                }
            )
    for index, item in enumerate(sorted(locks, key=lambda value: value["sort"]), 1):
        item.pop("sort")
        item["lock_key_id"] = index
        output["shared_locks"].append(item)
    commands = [str(details.get("command", "")) for _, details in cron_pairs]
    output["log_lock_refusals"] = _log_metrics(actx, commands)
    actx.rule_inputs["A3"] = {
        "shared_locks": output["shared_locks"],
        "log_lock_refusals": output["log_lock_refusals"],
    }


def _deployed_code_dirs(actx: ArchContext) -> list[str]:
    result = set()
    for entry in actx.files("worktree"):
        parts = Path(entry.rel).parts
        for index in range(len(parts) - 1):
            if parts[index] == "local" and parts[index + 1] in {
                "modules",
                "tools",
                "php_interface",
            }:
                result.add(Path(*parts[: index + 2]).as_posix())
    return sorted(result)


def _live_dirs(actx: ArchContext, units: list[dict]) -> set[Path]:
    result = set()
    for unit in units:
        entry = unit.get("entry")
        if isinstance(entry, str):
            result.add((actx.root / entry).parent)
    for unit, details in _runtime_pairs(actx):
        if unit.get("intersects_root") is not True:
            continue
        working = details.get("working_directory")
        if isinstance(working, str):
            candidate = Path(os.path.abspath(Path(working).expanduser()))
            if path_inside(candidate, actx.root):
                result.add(candidate)
    return result


def _i1_i2(actx: ArchContext, output: dict, units: list[dict]) -> None:
    tree = actx.out.get("tree", {})
    vcs = tree.get("vcs", {}) if isinstance(tree, dict) else {}
    reason = vcs.get("reason") if isinstance(vcs, dict) else "absent"
    deployed = _deployed_code_dirs(actx)
    actx.rule_inputs["I1"] = {
        "vcs_present": False,
        "reason": reason,
        "deployed_code_dirs": deployed,
        "live_units": len(units),
    }
    directories = _live_dirs(actx, units)
    recent = 0
    destructive = 0
    cutoff = time.time() - 24 * 60 * 60
    for entry in actx.files("worktree"):
        if not any(path_inside(entry.path, directory) for directory in directories):
            continue
        if entry.mtime >= cutoff:
            recent += 1
        if Path(entry.rel).suffix.lower() not in CODE_EXTENSIONS:
            continue
        data = actx.read(entry, max_bytes=20 * 1024 * 1024)
        if data is not None:
            destructive += len(DESTRUCTIVE_CALL.findall(data))
    output["recently_modified_in_live_dirs"] = recent
    output["destructive_api_calls"] = destructive
    actx.rule_inputs["I2"] = {
        "live_units": len(units),
        "vcs_present": False,
        "recent_files": recent,
        "destructive_calls": destructive,
    }


def _copy_key(rel: str) -> str:
    parts = Path(rel).parts
    indexes = [index for index, part in enumerate(parts) if part == "local"]
    if indexes:
        return Path(*parts[indexes[-1] :]).as_posix()
    parent = parts[:-1]
    return Path(*((*parent[-2:], parts[-1]) if parent else (parts[-1],))).as_posix()


def _i3(actx: ArchContext) -> tuple[list[dict], dict]:
    grouped: dict[str, list[object]] = {}
    hints = set()
    cap = min(20, actx.ctx.flags.max_hash_mb) * 1024 * 1024
    for entry in actx.files("worktree"):
        path = Path(entry.rel)
        if path.suffix.lower() not in CODE_EXTENSIONS or entry.size > cap or entry.is_symlink:
            continue
        grouped.setdefault(_copy_key(entry.rel), []).append(entry)
        if any(HINT_DIR.match(part) for part in path.parts[:-1]):
            hints.add(path.parent.as_posix())
    output = []
    max_copies = 0
    for rel, entries in sorted(grouped.items()):
        max_copies = max(max_copies, len(entries))
        if len(entries) < 3:
            continue
        by_size: dict[int, list[object]] = {}
        for entry in entries:
            by_size.setdefault(entry.size, []).append(entry)
        distinct = 0
        for same_size in by_size.values():
            if len(same_size) == 1:
                distinct += 1
                continue
            hashes = set()
            for entry in same_size:
                data = actx.read(entry, max_bytes=cap)
                if data is not None:
                    hashes.add(hashlib.sha1(data).digest())
            distinct += len(hashes)
        if distinct < 2:
            continue
        output.append(
            {
                "relpath": rel,
                "copies": len(entries),
                "distinct_hashes": distinct,
                "paths": sorted(entry.rel for entry in entries)[:10],
            }
        )
    return output, {
        "groups": len(grouped),
        "max_copies": max_copies,
        "hint_dirs": sorted(hints),
    }


def _integration_rules(actx: ArchContext, output: dict) -> None:
    scripts = actx.out.setdefault("scripts_collection", {})
    if actx.vcs:
        scripts.setdefault("copies_by_relpath", [])
        for rule in ("I1", "I2", "I3"):
            actx.rule_inputs[rule] = {"applicable": False}
        return
    units = _relevant_units(actx) or []
    _i1_i2(actx, output, units)
    copies, facts = _i3(actx)
    scripts.setdefault("copies_by_relpath", copies)
    actx.rule_inputs["I3"] = facts


def run(actx: ArchContext) -> None:
    output = {
        "live_closure": [],
        "shared_locks": [],
        "log_lock_refusals": [],
        "recently_modified_in_live_dirs": 0,
        "destructive_api_calls": 0,
    }
    actx.out[KEY] = output
    if actx.vcs:
        _a1(actx, output)
        _a2(actx)
    else:
        actx.rule_inputs["A1"] = {"applicable": False}
        actx.rule_inputs["A2"] = {"applicable": False}
    _a3(actx, output)
    _integration_rules(actx, output)
