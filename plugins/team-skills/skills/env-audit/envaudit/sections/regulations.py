from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from envaudit.core.context import Context
from envaudit.core.dates import status_date
from envaudit.core.docs_layout import ROOT_FILE_KINDS, detect_prefix, locate_root_file
from envaudit.core import runner
from envaudit.core.walk import iter_files


NAME = "regulations"
ORDER = 90

_SUPERPOWERS = "superpowers@claude-plugins-official"
_SERVICE_DOCS = ("ACCEPTANCE.md", "ADMIN-RUNBOOK.md", "USER-GUIDE.md")
_FILE_COUNT_CAP = 10_000


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _date_part(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"20\d\d-\d\d-\d\d", value)
    return match.group(0) if match else None


def _home_path(value: str, home: Path) -> Path:
    if value == "~":
        return home
    if value.startswith("~/"):
        return home / value[2:]
    return Path(value)


def _display_path(path: Path, home: Path) -> str:
    try:
        relative = path.relative_to(home)
    except ValueError:
        return str(path)
    return "~" if not relative.parts else f"~/{relative.as_posix()}"


def _strip_url_credentials(value: str) -> str:
    if "://" not in value:
        return value
    scheme, remainder = value.split("://", 1)
    authority, separator, tail = remainder.partition("/")
    if "@" in authority:
        authority = authority.rsplit("@", 1)[1]
    return f"{scheme}://{authority}{separator}{tail}"


def _marketplace_source(item: object, home: Path) -> tuple[str, str | None]:
    source = item.get("source") if isinstance(item, dict) else None
    if isinstance(source, dict):
        repo = source.get("repo")
        url = source.get("url")
        path = source.get("path")
        marker = source.get("source")
        if isinstance(repo, str) and repo:
            return "github", repo
        if isinstance(url, str) and url:
            return "git", _strip_url_credentials(url)
        if isinstance(path, str) and path:
            return "directory", _display_path(_home_path(path, home), home)
        if isinstance(marker, str) and marker:
            if marker.startswith(("/", "~")):
                return "directory", _display_path(_home_path(marker, home), home)
            return "other", marker
        return "other", None
    if isinstance(source, str) and source:
        if source.startswith(("/", "~")):
            return "directory", _display_path(_home_path(source, home), home)
        return "other", source
    return "other", None


def _is_skill_exchange_source(item: object) -> bool:
    source = item.get("source") if isinstance(item, dict) else None
    if isinstance(source, dict):
        candidates = (source.get(key) for key in ("repo", "url", "path"))
    else:
        candidates = (source,)
    return any(
        isinstance(value, str)
        and "skill-exchange_arbitra" in value.removesuffix(".git").casefold()
        for value in candidates
    )


def _fetch_date(repo: Path) -> str | None:
    fetch_head = repo / ".git" / "FETCH_HEAD"
    try:
        modified = datetime.fromtimestamp(fetch_head.stat().st_mtime, timezone.utc)
    except OSError:
        return None
    return modified.date().isoformat()


def _directory_checkout(source: str, home: Path) -> dict:
    path = _home_path(source, home)
    is_git = runner.is_git_repo(path)
    behind: int | None = None
    if is_git:
        result = runner.git(path, "rev-list", "--count", "HEAD..@{u}")
        if result.rc == 0:
            try:
                behind = int(result.stdout.strip())
            except ValueError:
                pass
    return {
        "path": _display_path(path, home),
        "is_git": is_git,
        "behind_tracking": behind,
        "last_fetch_date": _fetch_date(path),
    }


def _r1_exchange(ctx: Context) -> dict:
    path = ctx.home / ".claude" / "plugins" / "known_marketplaces.json"
    data = _read_json(path)
    marketplaces = []
    exchange_present = False
    official_present = False
    checkout = None
    for name in sorted(data):
        item = data[name]
        source_kind, source = _marketplace_source(item, ctx.home)
        auto_update = item.get("autoUpdate") if isinstance(item, dict) else None
        marketplaces.append(
            {
                "name": str(name),
                "source_kind": source_kind,
                "source": source,
                "auto_update": auto_update if isinstance(auto_update, bool) else None,
                "last_updated": _date_part(
                    item.get("lastUpdated") if isinstance(item, dict) else None
                ),
            }
        )
        if name == "claude-plugins-official":
            official_present = True
        if _is_skill_exchange_source(item):
            exchange_present = True
            if source_kind == "directory" and checkout is None:
                checkout = _directory_checkout(source, ctx.home)
    return {
        "marketplaces": marketplaces,
        "skill_exchange_present": exchange_present,
        "official_present": official_present,
        "directory_checkout": checkout,
    }


def _numbered_folder(docs: Path, number: int) -> bool:
    try:
        return any(path.is_dir() for path in docs.glob(f"{number}.*"))
    except OSError:
        return False


def _r2_docs(ctx: Context) -> dict:
    result = {}
    for root in ctx.roots:
        docs = root / "docs"
        if not (root.joinpath(".git").exists() or docs.is_dir()):
            continue
        prefix = detect_prefix(root)
        result[str(root)] = {
            "docs_dir": docs.is_dir(),
            "prefix": prefix,
            "folders": {
                **{str(number): _numbered_folder(docs, number) for number in range(1, 6)},
                "backlog": (docs / "backlog").is_dir(),
            },
            "root_files": {
                kind: locate_root_file(root, prefix, kind)[0]
                for kind in ROOT_FILE_KINDS
            },
            "service_docs": [
                name for name in _SERVICE_DOCS if (root / name).is_file()
            ],
            "superpowers_dir": (docs / "superpowers").is_dir(),
        }
    return result


def _gh_hosts(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    hosts = []
    for line in lines:
        if not line or line[0].isspace() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([^:#][^:]*)\s*:\s*(?:#.*)?$", line)
        if match:
            host = match.group(1).strip().strip("\"'")
            if host:
                hosts.append(host)
    return sorted(set(hosts))


def _remote_parts(raw: str) -> tuple[str | None, str | None]:
    value = raw.strip()
    if "://" in value:
        value = _strip_url_credentials(value)
        parsed = urlsplit(value)
        host = parsed.hostname
        repo = parsed.path.lstrip("/")
    else:
        if "@" in value.partition(":")[0]:
            value = value.split("@", 1)[1]
        match = re.match(r"^(?:[^@/:]+@)?([^/:]+):(.+)$", value)
        if not match:
            return None, None
        host, repo = match.groups()
    repo = repo.removesuffix(".git").rstrip("/")
    return host or None, repo or None


def _count_files(root: Path, ctx: Context) -> tuple[int, bool]:
    count = 0
    for _entry in iter_files(root, ctx, NAME):
        if count == _FILE_COUNT_CAP:
            return count, True
        count += 1
    return count, False


def _r4_github(ctx: Context) -> dict:
    config = ctx.home / ".config" / "gh" / "hosts.yml"
    roots = {}
    for root in ctx.roots:
        vcs = runner.is_git_repo(root)
        item = {
            "vcs": vcs,
            "origin_host": None,
            "origin_repo": None,
            "upstream": False,
            "files": None,
            "has_docs": (root / "docs").is_dir(),
        }
        if vcs:
            origin = runner.git(root, "remote", "get-url", "origin")
            if origin.rc == 0:
                item["origin_host"], item["origin_repo"] = _remote_parts(
                    origin.stdout.decode("utf-8", errors="replace")
                )
            upstream = runner.git(root, "rev-parse", "--abbrev-ref", "@{u}")
            item["upstream"] = upstream.rc == 0
        else:
            item["files"], capped = _count_files(root, ctx)
            if capped:
                item["files_capped"] = True
        roots[str(root)] = item
    return {
        "gh_config_present": config.is_file(),
        "gh_hosts": _gh_hosts(config),
        "roots": roots,
    }


def _team_context_lines(path: Path) -> int:
    try:
        return sum(
            "BEGIN team-context" in line
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        )
    except OSError:
        return 0


def _memory_dirs_nonempty(home: Path) -> int:
    base = home / ".claude" / "projects"
    try:
        memories = (path / "memory" for path in base.iterdir() if path.is_dir())
        return sum(
            1
            for memory in memories
            if memory.is_dir() and any(path.is_file() for path in memory.glob("*.md"))
        )
    except OSError:
        return 0


def _r5_levels(ctx: Context, codex_home: Path) -> dict:
    global_claude = ctx.home / ".claude" / "CLAUDE.md"
    global_codex = codex_home / "AGENTS.md"
    return {
        "global_claude_md": global_claude.is_file(),
        "global_claude_team_context": _team_context_lines(global_claude),
        "global_codex_agents_md": global_codex.is_file(),
        "global_codex_team_context": _team_context_lines(global_codex),
        "projects": {
            str(root): {
                "claude_md": (root / "CLAUDE.md").is_file(),
                "agents_md": (root / "AGENTS.md").is_file(),
                "agents_md_team_context": _team_context_lines(root / "AGENTS.md"),
            }
            for root in ctx.roots
        },
        "memory_dirs_nonempty": _memory_dirs_nonempty(ctx.home),
    }


def _version_tuple(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"\d+(?:\.\d+)+", value)
    return tuple(int(part) for part in match.group(0).split(".")) if match else None


def _version_at_least(value: object, minimum: tuple[int, ...]) -> bool:
    parsed = _version_tuple(value)
    if parsed is None:
        return False
    width = max(len(parsed), len(minimum))
    return parsed + (0,) * (width - len(parsed)) >= minimum + (0,) * (
        width - len(minimum)
    )


def _r6_codex(ctx: Context, codex_home: Path, host: dict) -> dict:
    version = host.get("codex_version")
    return {
        "codex_version": version if isinstance(version, str) else None,
        "version_at_least_0_146": _version_at_least(version, (0, 146, 0)),
        "global_agents_md": (codex_home / "AGENTS.md").is_file(),
        "projects_claude_without_agents": [
            str(root)
            for root in ctx.roots
            if (root / "CLAUDE.md").is_file() and not (root / "AGENTS.md").is_file()
        ],
        "codex_json": {
            str(root): (root / ".claude" / "codex.json").is_file()
            for root in ctx.roots
        },
    }


def _docker_version(executable: str) -> str | None:
    result = runner.run([executable, "--version"], timeout=10)
    if result.rc != 0:
        return None
    match = re.search(rb"\d+\.\d+\.\d+", result.stdout)
    return match.group(0).decode("ascii") if match else None


def _has_code(root: Path, ctx: Context) -> bool:
    for entry in iter_files(root, ctx, NAME, max_depth=2):
        if entry.path.name == "package.json" or entry.path.suffix in {
            ".py",
            ".go",
            ".php",
        }:
            return True
    return False


def _container_files(root: Path) -> list[str]:
    try:
        paths = root.iterdir()
        return sorted(
            path.name
            for path in paths
            if path.is_file()
            and (
                path.name.startswith("Dockerfile")
                or re.fullmatch(r"docker-compose.*\.ya?ml", path.name)
                or re.fullmatch(r"compose.*\.ya?ml", path.name)
            )
        )
    except OSError:
        return []


def _r7_docker(ctx: Context) -> dict:
    executable = runner.which("docker")
    if executable is None:
        version = None
        reachable = None
    else:
        version = _docker_version(executable)
        reachable = (
            runner.run(
                [executable, "info", "--format", "{{.ServerVersion}}"],
                timeout=10,
            ).rc
            == 0
        )
    return {
        "docker_version": version,
        "daemon_reachable": reachable,
        "roots": {
            str(root): {
                "has_code": _has_code(root, ctx),
                "container_files": _container_files(root),
            }
            for root in ctx.roots
        },
    }


def _frontmatter(lines: list[str]) -> tuple[str | None, str | None, str | None]:
    name = None
    top_type = None
    metadata_type = None
    parent = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^(\s*)([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", line)
        if not match:
            continue
        indent, key, value = match.groups()
        value = value.strip().strip("\"'") or None
        if not indent:
            parent = key if value is None else None
            if key == "name":
                name = value
            elif key == "type":
                top_type = value
        elif parent == "metadata" and key == "type":
            metadata_type = value
    return name, top_type, metadata_type


def _card_text(path: Path) -> tuple[str, list[str]] | None:
    if path.is_symlink():
        return None
    head = []
    frontmatter = []
    in_frontmatter = False
    finished_frontmatter = False
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for number, line in enumerate(stream):
                if number < 30:
                    head.append(line)
                stripped = line.strip()
                if number == 0 and stripped == "---":
                    in_frontmatter = True
                elif in_frontmatter and stripped == "---":
                    in_frontmatter = False
                    finished_frontmatter = True
                elif in_frontmatter:
                    frontmatter.append(line.rstrip("\n"))
                if number >= 29 and (not in_frontmatter or finished_frontmatter):
                    break
    except OSError:
        return None
    return "".join(head), frontmatter


def _card_view(path: Path, memory_dir: str, head: str) -> dict:
    date = status_date(path, head)
    return {
        "memory_dir": memory_dir,
        "file": path.name,
        "date": date.date,
        "date_source": date.source,
        "date_trust": date.trust,
    }


def _r8_r10_memory(ctx: Context) -> dict:
    groups = {"bitrix_regulation": [], "principles": [], "user_profile": []}
    base = ctx.home / ".claude" / "projects"
    try:
        project_dirs = sorted(
            (path for path in base.iterdir() if path.is_dir()),
            key=lambda path: path.name,
        )
    except OSError:
        return groups
    for project_dir in project_dirs:
        memory = project_dir / "memory"
        try:
            cards = sorted(memory.glob("*.md"), key=lambda path: path.name)
        except OSError:
            continue
        for path in cards:
            if path.name == "MEMORY.md" or not path.is_file():
                continue
            content = _card_text(path)
            if content is None:
                continue
            head, frontmatter_lines = content
            name, top_type, metadata_type = _frontmatter(frontmatter_lines)
            lowered_head = head.casefold()
            identity = f"{name or ''}\n{path.name}".casefold()
            card = _card_view(path, project_dir.name, head)
            if ("bitrix" in identity or "битрикс" in identity) and re.search(
                r"регламент|задач|task", lowered_head
            ):
                groups["bitrix_regulation"].append(card)
            if "честност" in lowered_head and "документ" in lowered_head:
                groups["principles"].append(card)
            if (top_type or "").casefold() == "user" or (
                metadata_type or ""
            ).casefold() == "user":
                groups["user_profile"].append(card)
    return groups


def _installed_plugins(home: Path) -> dict:
    data = _read_json(home / ".claude" / "plugins" / "installed_plugins.json")
    plugins = data.get("plugins")
    return plugins if isinstance(plugins, dict) else {}


def _plugin_version(value: object) -> str | None:
    entries = value if isinstance(value, list) else [value]
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("version"), str):
            return entry["version"]
    return None


def _r11_superpowers(ctx: Context, plugins: dict) -> dict:
    installed = _SUPERPOWERS in plugins
    version = _plugin_version(plugins.get(_SUPERPOWERS))
    settings = _read_json(ctx.home / ".claude" / "settings.json")
    enabled_plugins = settings.get("enabledPlugins")
    enabled = bool(
        isinstance(enabled_plugins, dict) and enabled_plugins.get(_SUPERPOWERS) is True
    )
    return {
        "installed": installed,
        "version": version,
        "version_at_least_6_2_0": _version_at_least(version, (6, 2, 0)),
        "enabled": enabled,
    }


def _directory_count(path: Path) -> int:
    try:
        return sum(item.is_dir() for item in path.iterdir())
    except OSError:
        return 0


def _r3_sources(ctx: Context, plugins: dict) -> dict:
    return {
        "installed_plugins": sorted(str(name) for name in plugins),
        "user_skills": _directory_count(ctx.home / ".claude" / "skills"),
        "project_skills": {
            str(root): _directory_count(root / ".claude" / "skills")
            for root in ctx.roots
        },
    }


def collect(ctx: Context) -> dict:
    host = ctx.shared.get("host")
    host = host if isinstance(host, dict) else {}
    codex_home_raw = host.get("codex_home")
    codex_home = (
        Path(codex_home_raw)
        if isinstance(codex_home_raw, str)
        else ctx.home / ".codex"
    )
    codex_profile = host.get("profile") == "codex"
    if codex_profile:
        ctx.skip(NAME, "not_applicable", "profile=codex")
        r1_exchange = None
        r3_sources = None
        r11_superpowers = None
    else:
        plugins = _installed_plugins(ctx.home)
        r1_exchange = _r1_exchange(ctx)
        r3_sources = _r3_sources(ctx, plugins)
        r11_superpowers = _r11_superpowers(ctx, plugins)

    return {
        "r1_exchange": r1_exchange,
        "r2_docs": _r2_docs(ctx),
        "r4_github": _r4_github(ctx),
        "r5_levels": _r5_levels(ctx, codex_home),
        "r6_codex": _r6_codex(ctx, codex_home, host),
        "r7_docker": _r7_docker(ctx),
        "r8_r10_memory": _r8_r10_memory(ctx),
        "r11_superpowers": r11_superpowers,
        "r3_sources": r3_sources,
    }
