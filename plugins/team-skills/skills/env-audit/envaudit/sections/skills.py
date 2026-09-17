from collections.abc import Mapping
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from envaudit.core import runner
from envaudit.core.context import Context
from envaudit.core.skills_index import (
    MANDATORY,
    MANAGED_DIRS,
    SkillEntry,
    list_skills,
    overrides,
    plugin_twins,
    resolve,
)
from envaudit.core.transcripts import Record, load_index, skill_usage
from envaudit.core.walk import iter_files, read_limited


NAME = "skills"
ORDER = 40

_INSTRUCTION_NAMES = frozenset({"CLAUDE.md", "AGENTS.md"})
_DISABLED = frozenset({"off", "user-invocable-only"})


def _read_json(path: Path) -> Mapping | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _inside(path: Path | str, root: Path | str) -> bool:
    try:
        real_root = os.path.realpath(root)
        return os.path.commonpath((os.path.realpath(path), real_root)) == real_root
    except (OSError, ValueError):
        return False


def _cwd_chain(cwd: Path, home: Path) -> list[Path]:
    current = Path(os.path.realpath(cwd))
    stop = Path(os.path.realpath(home)) if _inside(current, home) else current.anchor
    if runner.is_git_repo(current):
        result = runner.git(current, "rev-parse", "--show-toplevel")
        if result.rc == 0:
            raw = result.stdout.decode("utf-8", errors="replace").strip()
            if raw:
                stop = Path(os.path.realpath(raw))

    chain = []
    while True:
        chain.append(current)
        if str(current) == str(stop) or current.parent == current:
            break
        current = current.parent
    return chain


def _instruction_texts(root: Path, ctx: Context) -> list[str]:
    texts = []
    limit = max(ctx.flags.max_text_mb, 1) * 1024 * 1024
    for entry in iter_files(root, ctx, NAME, max_depth=3):
        if entry.path.name not in _INSTRUCTION_NAMES:
            continue
        raw = read_limited(entry, limit)
        if raw is not None:
            texts.append(raw.decode("utf-8", errors="replace"))
    return texts


def _referenced_names(entries: list[SkillEntry], texts: list[str]) -> set[str]:
    result = set()
    joined = "\n".join(texts)
    for name in {item.name for item in entries}:
        pattern = re.compile(
            rf"(?<![\w-])/?(?:[\w-]+:)?{re.escape(name)}(?![\w-])"
        )
        if pattern.search(joined):
            result.add(name)
    return result


def _effective_override(
    name: str, settings: dict[str, dict[str, str]]
) -> str | None:
    for level in ("project_local", "project", "user"):
        value = settings[level].get(name)
        if value is not None:
            return value
    return None


def _date(value: float | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _invocations(entry: SkillEntry, records: list[Record]) -> tuple[int, str | None]:
    timestamps = []
    for record in records:
        names = []
        if record.command_name:
            names.append(record.command_name)
        names.extend(
            tool.skill
            for tool in record.tool_uses
            if tool.name == "Skill" and tool.skill
        )
        expected = entry.qualified if entry.source == "plugin" else entry.name
        if expected in names and record.timestamp is not None:
            timestamps.append(record.timestamp)
    return len(timestamps), _date(max(timestamps)) if timestamps else None


def _usage(entry: SkillEntry, usage: dict[str, dict]) -> dict:
    raw = usage.get(entry.qualified)
    if raw is None:
        raw = usage.get(entry.name)
    if not isinstance(raw, dict):
        return {"usage_count": 0, "last_used_at": None}
    count = raw.get("usage_count")
    used_at = raw.get("last_used_at")
    return {
        "usage_count": count if isinstance(count, int) and not isinstance(count, bool) else 0,
        "last_used_at": _date(used_at) if isinstance(used_at, (int, float)) else None,
    }


def _entry_view(
    entry: SkillEntry,
    setting: str | None,
    referenced: set[str],
    records: list[Record],
    usage: dict[str, dict],
) -> dict:
    reasons = []
    if entry.name in MANDATORY:
        reasons.append("mandatory")
    if entry.namespace == "superpowers":
        reasons.append("superpowers")
    if entry.name == "env-audit":
        reasons.append("env_audit")
    if entry.name in referenced:
        reasons.append("referenced")
    count, last = _invocations(entry, records)
    return {
        "qualified": entry.qualified,
        "name": entry.name,
        "namespace": entry.namespace,
        "source": entry.source,
        "plugin_version": entry.plugin_version,
        "description_len": entry.description_len,
        "when_to_use_len": entry.when_to_use_len,
        "has_cyrillic": entry.has_cyrillic,
        "override": setting,
        "override_effective": entry.source != "plugin",
        "protected": bool(reasons),
        "protected_reasons": reasons,
        "invocations_window": count,
        "last_invoked_at": last,
        "skill_usage": _usage(entry, usage),
    }


def _path_rel(path: Path, root: Path, home: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        try:
            return "~/" + path.relative_to(home).as_posix()
        except ValueError:
            return str(path)


def _root_view(
    root: Path,
    entries: list[SkillEntry],
    settings: dict[str, dict[str, str]],
    referenced: set[str],
    home: Path,
) -> dict:
    names = sorted(
        {item.name for item in entries if item.source != "plugin"} | set(MANDATORY)
    )
    resolved = {}
    for name in names:
        item = resolve(name, entries)
        resolved[name] = (
            {
                "qualified": item.qualified,
                "source": item.source,
                "path_rel": _path_rel(item.path, root, home),
            }
            if item is not None
            else None
        )

    grouped: dict[str, list[SkillEntry]] = {}
    for item in entries:
        if item.source != "plugin":
            grouped.setdefault(item.name, []).append(item)
    shadowed = [
        {
            "name": name,
            "sources": list(
                dict.fromkeys(item.source for item in grouped[name])
            ),
        }
        for name in sorted(grouped)
        if len(grouped[name]) >= 2
    ]
    twins = {
        name: values
        for name in sorted(grouped)
        if (values := plugin_twins(name, entries))
    }
    return {
        "resolved": resolved,
        "shadowed_non_plugin": shadowed,
        "plugin_twins": twins,
        "overrides": {
            "project": settings["project"],
            "project_local": settings["project_local"],
        },
        "referenced_in_instructions": sorted(referenced),
    }


def _installed_plugins(home: Path, ctx: Context) -> tuple[Mapping, Mapping]:
    path = home / ".claude" / "plugins" / "installed_plugins.json"
    installed = _read_json(path)
    if path.exists() and installed is None:
        ctx.error(NAME, "installed_plugins_unreadable")
    plugins = installed.get("plugins") if installed is not None else None
    settings = _read_json(home / ".claude" / "settings.json") or {}
    enabled = settings.get("enabledPlugins")
    return (
        plugins if isinstance(plugins, Mapping) else {},
        enabled if isinstance(enabled, Mapping) else {},
    )


def _plugin_skill_names(row: Mapping) -> set[str]:
    raw_path = row.get("installPath")
    if not isinstance(raw_path, str):
        return set()
    try:
        return {path.parent.name for path in Path(raw_path).glob("skills/*/SKILL.md")}
    except OSError:
        return set()


def _superpowers(
    plugins: Mapping,
    enabled: Mapping,
    entries: list[SkillEntry],
    entry_settings: dict[Path, str | None],
) -> dict:
    keys = sorted(
        key
        for key in plugins
        if isinstance(key, str) and key.split("@", 1)[0] == "superpowers"
    )
    names = set()
    for key in keys:
        rows = plugins[key]
        if isinstance(rows, list) and rows and isinstance(rows[-1], Mapping):
            names.update(_plugin_skill_names(rows[-1]))
    disabled = sorted(
        {
            item.name
            for item in entries
            if item.source != "plugin"
            and item.name in names
            and entry_settings.get(item.path) in _DISABLED
        }
    )
    return {
        "installed": bool(keys),
        "enabled": any(enabled.get(key) is True for key in keys),
        "disabled_by_override": disabled,
    }


def _actual_listing(index, roots: list[Path]) -> list[dict]:
    actual = []
    for root in roots:
        candidates: list[Record] = []
        for records in index.sessions().values():
            if not any(record.cwd and _inside(record.cwd, root) for record in records):
                continue
            candidates.extend(
                record
                for record in records
                if record.attachment_type == "skill_listing"
                and record.attachment_len is not None
            )
        if not candidates:
            continue
        record = max(
            candidates,
            key=lambda item: (item.timestamp or 0.0, item.line_no),
        )
        actual.append(
            {
                "root": str(root),
                "length": record.attachment_len,
                "skill_count": record.skill_count,
                "date": _date(record.timestamp),
            }
        )
    return actual


def _latest_model(index) -> str | None:
    records = [
        record
        for record in index.records
        if record.model is not None and record.timestamp is not None
    ]
    return max(records, key=lambda item: item.timestamp or 0.0).model if records else None


def _listing(
    home: Path,
    entries: list[SkillEntry],
    entry_settings: dict[Path, str | None],
    index,
    roots: list[Path],
) -> dict:
    settings = _read_json(home / ".claude" / "settings.json") or {}
    raw_fraction = settings.get("skillListingBudgetFraction")
    fraction = (
        float(raw_fraction)
        if isinstance(raw_fraction, (int, float))
        and not isinstance(raw_fraction, bool)
        and raw_fraction > 0
        else 0.01
    )
    raw_maximum = settings.get("skillListingMaxDescChars")
    maximum = (
        raw_maximum
        if isinstance(raw_maximum, int)
        and not isinstance(raw_maximum, bool)
        and raw_maximum > 0
        else 1536
    )
    configured_model = settings.get("model")
    latest_model = _latest_model(index)
    model_1m = any(
        isinstance(value, str) and "[1m]" in value
        for value in (configured_model, latest_model)
    )
    window = 1_000_000 if model_1m else 200_000
    raw_sum = sum(
        min(item.description_len + item.when_to_use_len, maximum)
        for item in entries
        if item.source == "plugin" or entry_settings.get(item.path) not in _DISABLED
    )
    source = "settings" if any(
        key in settings
        for key in ("model", "skillListingBudgetFraction", "skillListingMaxDescChars")
    ) else "defaults"
    return {
        "actual": _actual_listing(index, roots),
        "raw_sum_chars": raw_sum,
        "formula": {
            "model_window_tokens": window,
            "budget_chars": int(window * 4 * fraction),
            "max_desc_chars": maximum,
            "budget_fraction": fraction,
            "source": source,
        },
    }


def collect(ctx: Context) -> dict:
    index = load_index(ctx)
    root_entries: dict[Path, list[SkillEntry]] = {}
    root_settings: dict[Path, dict[str, dict[str, str]]] = {}
    root_references: dict[Path, set[str]] = {}
    all_entries: dict[Path, SkillEntry] = {}
    all_referenced = set()

    for root in ctx.roots:
        entries = list_skills(ctx.home, _cwd_chain(root, ctx.home))
        root_entries[root] = entries
        settings = overrides(ctx.home, root)
        root_settings[root] = settings
        referenced = _referenced_names(entries, _instruction_texts(root, ctx))
        root_references[root] = referenced
        all_referenced.update(referenced)
        for item in entries:
            all_entries.setdefault(Path(os.path.realpath(item.path)), item)

    if not ctx.roots:
        entries = list_skills(ctx.home, [])
        for item in entries:
            all_entries.setdefault(Path(os.path.realpath(item.path)), item)

    entries = sorted(
        all_entries.values(), key=lambda item: (item.qualified, item.source, str(item.path))
    )
    user_settings = overrides(ctx.home, None)["user"]
    entry_settings: dict[Path, str | None] = {}
    for item in entries:
        setting = user_settings.get(item.name)
        for root in ctx.roots:
            root_setting = _effective_override(item.name, root_settings[root])
            if root_setting is not None:
                setting = root_setting
                break
        entry_settings[item.path] = setting

    usage = skill_usage(ctx.home)
    views = [
        _entry_view(
            item,
            entry_settings[item.path],
            all_referenced,
            index.records,
            usage,
        )
        for item in entries
    ]
    present = {
        name: sorted({item.qualified for item in entries if item.name == name})
        for name in MANDATORY
        if any(item.name == name for item in entries)
    }
    missing = [name for name in MANDATORY if name not in present]
    disabled = sorted(
        {
            item.name
            for item in entries
            if item.name in MANDATORY
            and item.source != "plugin"
            and entry_settings[item.path] in _DISABLED
        }
    )
    plugins, enabled = _installed_plugins(ctx.home, ctx)
    return {
        "managed_dirs_checked": [str(path) for path in MANAGED_DIRS],
        "entries": views,
        "roots": {
            str(root): _root_view(
                root,
                root_entries[root],
                root_settings[root],
                root_references[root],
                ctx.home,
            )
            for root in ctx.roots
        },
        "overrides_user": user_settings,
        "mandatory": {"present": present, "missing": missing, "disabled": disabled},
        "superpowers": _superpowers(plugins, enabled, entries, entry_settings),
        "listing": _listing(ctx.home, entries, entry_settings, index, ctx.roots),
        "window_days": index.window_days,
    }
