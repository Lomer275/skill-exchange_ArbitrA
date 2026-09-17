from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re


MANDATORY = (
    "intro",
    "close",
    "agents-context",
    "impl",
    "fix",
    "codereview",
    "review-loop",
    "spec-writer",
    "accept",
    "init_dev",
)
MANAGED_DIRS = (
    Path("/etc/claude-code/.claude/skills"),
    Path("/etc/claude-code/skills"),
)

_SOURCE_ORDER = {
    "managed": 0,
    "user": 1,
    "project": 2,
    "user_command": 3,
    "project_command": 4,
}
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$")


@dataclass(frozen=True)
class SkillEntry:
    name: str
    namespace: str | None
    source: str
    path: Path
    plugin_key: str | None
    plugin_version: str | None
    description_len: int
    when_to_use_len: int
    has_cyrillic: bool

    @property
    def qualified(self) -> str:
        if self.namespace:
            return f"{self.namespace}:{self.name}"
        return self.name


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next(
        (index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"),
        None,
    )
    if end is None:
        return {}

    result: dict[str, str] = {}
    index = 1
    while index < end:
        match = _KEY_RE.match(lines[index])
        if match is None:
            index += 1
            continue
        key, raw = match.groups()
        if raw in {">", "|", ">-", "|-", ">+", "|+"}:
            separator = " " if raw.startswith(">") else "\n"
            parts = []
            index += 1
            while index < end:
                line = lines[index]
                if line and not line[0].isspace():
                    break
                stripped = line.strip()
                if stripped:
                    parts.append(stripped)
                index += 1
            result[key] = separator.join(parts)
            continue
        result[key] = _unquote(raw.strip())
        index += 1
    return result


def _frontmatter_text(path: Path) -> str | None:
    lines = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for number, line in enumerate(stream):
                lines.append(line)
                if number == 0 and line.strip() != "---":
                    return ""
                if number > 0 and line.strip() == "---":
                    break
                if number >= 10_000:
                    return None
    except OSError:
        return None
    if len(lines) < 2 or lines[-1].strip() != "---":
        return ""
    return "".join(lines)


def _entry(
    path: Path,
    source: str,
    *,
    namespace: str | None = None,
    plugin_key: str | None = None,
    plugin_version: str | None = None,
) -> SkillEntry | None:
    text = _frontmatter_text(path)
    if text is None:
        return None
    frontmatter = parse_frontmatter(text)
    fallback_name = path.parent.name if path.name == "SKILL.md" else path.stem
    name = frontmatter.get("name") or fallback_name
    description = frontmatter.get("description", "")
    when_to_use = frontmatter.get("when_to_use", frontmatter.get("whenToUse", ""))
    return SkillEntry(
        name=name,
        namespace=namespace,
        source=source,
        path=path,
        plugin_key=plugin_key,
        plugin_version=plugin_version,
        description_len=len(description.replace("\n", "")),
        when_to_use_len=len(when_to_use.replace("\n", "")),
        has_cyrillic=_CYRILLIC_RE.search(description) is not None,
    )


def _skill_paths(base: Path) -> Iterable[Path]:
    try:
        yield from sorted(base.glob("*/SKILL.md"), key=lambda item: str(item))
    except OSError:
        return


def _command_paths(base: Path) -> Iterable[Path]:
    try:
        yield from sorted(base.rglob("*.md"), key=lambda item: str(item))
    except OSError:
        return


def _json_mapping(path: Path) -> Mapping:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _plugin_entries(home: Path) -> Iterable[SkillEntry]:
    installed = _json_mapping(home / ".claude" / "plugins" / "installed_plugins.json")
    plugins = installed.get("plugins")
    if not isinstance(plugins, Mapping):
        return
    settings = _json_mapping(home / ".claude" / "settings.json")
    enabled = settings.get("enabledPlugins")
    if not isinstance(enabled, Mapping):
        enabled = {}

    for key in sorted(plugins):
        rows = plugins[key]
        if not isinstance(key, str) or enabled.get(key) is not True:
            continue
        if not isinstance(rows, list) or not rows or not isinstance(rows[-1], Mapping):
            continue
        row = rows[-1]
        raw_path = row.get("installPath")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        version = row.get("version")
        plugin_version = version if isinstance(version, str) else None
        namespace = key.split("@", 1)[0]
        install_path = (
            home / raw_path[2:]
            if raw_path.startswith("~/")
            else Path(raw_path).expanduser()
        )
        for path in _skill_paths(install_path / "skills"):
            item = _entry(
                path,
                "plugin",
                namespace=namespace,
                plugin_key=key,
                plugin_version=plugin_version,
            )
            if item is not None:
                yield item
        for path in _command_paths(install_path / "commands"):
            item = _entry(
                path,
                "plugin",
                namespace=namespace,
                plugin_key=key,
                plugin_version=plugin_version,
            )
            if item is not None:
                yield item


def list_skills(home: Path, cwd_chain: list[Path]) -> list[SkillEntry]:
    entries: list[SkillEntry] = []

    def add(paths: Iterable[Path], source: str) -> None:
        for path in paths:
            item = _entry(path, source)
            if item is not None:
                entries.append(item)

    for directory in MANAGED_DIRS:
        add(_skill_paths(directory), "managed")
    add(_skill_paths(home / ".claude" / "skills"), "user")
    for directory in cwd_chain:
        add(_skill_paths(directory / ".claude" / "skills"), "project")
    add(_command_paths(home / ".claude" / "commands"), "user_command")
    for directory in cwd_chain:
        add(_command_paths(directory / ".claude" / "commands"), "project_command")
    entries.extend(_plugin_entries(home))

    unique: dict[Path, SkillEntry] = {}
    for item in entries:
        try:
            key = Path(os.path.realpath(item.path))
        except OSError:
            key = item.path
        unique.setdefault(key, item)
    return list(unique.values())


def resolve(name: str, entries: list[SkillEntry]) -> SkillEntry | None:
    if ":" in name:
        namespace, bare = name.split(":", 1)
        return next(
            (
                item
                for item in entries
                if item.source == "plugin"
                and item.namespace == namespace
                and item.name == bare
            ),
            None,
        )
    candidates = [
        (index, item)
        for index, item in enumerate(entries)
        if item.source != "plugin" and item.name == name
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda pair: (_SOURCE_ORDER.get(pair[1].source, 99), pair[0]),
    )[1]


def plugin_twins(name: str, entries: list[SkillEntry]) -> list[str]:
    return sorted(
        {
            item.qualified
            for item in entries
            if item.source == "plugin" and item.name == name
        }
    )


def _skill_overrides(path: Path) -> dict[str, str]:
    raw = _json_mapping(path).get("skillOverrides")
    if not isinstance(raw, Mapping):
        return {}
    return {
        name: value
        for name, value in raw.items()
        if isinstance(name, str) and isinstance(value, str)
    }


def overrides(home: Path, root: Path | None) -> dict[str, dict[str, str]]:
    return {
        "user": _skill_overrides(home / ".claude" / "settings.json"),
        "project": (
            _skill_overrides(root / ".claude" / "settings.json") if root else {}
        ),
        "project_local": (
            _skill_overrides(root / ".claude" / "settings.local.json")
            if root
            else {}
        ),
    }


def memory_dir_name(path: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", os.path.realpath(path))
