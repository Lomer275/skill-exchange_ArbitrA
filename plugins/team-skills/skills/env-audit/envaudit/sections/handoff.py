from datetime import date, datetime, timezone
import fnmatch
import os
from pathlib import Path
import re

from envaudit.core import runner
from envaudit.core.context import Context
from envaudit.core.docs_layout import detect_prefix
from envaudit.core.skills_index import SkillEntry, list_skills, plugin_twins, resolve
from envaudit.core.transcripts import CODE_EXTS, Record, load_index
from envaudit.core.walk import iter_files
from envaudit.handoff.canon import find_canon
from envaudit.handoff.writes import WriteTarget, agents_md_close_section, write_targets


NAME = "handoff"
ORDER = 30

_COMMANDS = ("close", "intro", "accept")
_DAY = 86400


def _inside(path: Path | str, root: Path | str) -> bool:
    try:
        real_root = os.path.realpath(root)
        return os.path.commonpath((os.path.realpath(path), real_root)) == real_root
    except (OSError, ValueError):
        return False


def _cwd_chain(cwd: Path, home: Path) -> list[Path]:
    current = Path(os.path.realpath(cwd))
    home = Path(os.path.realpath(home))
    stop = home if _inside(current, home) else Path(current.anchor)
    if runner.is_git_repo(current):
        result = runner.git(current, "rev-parse", "--show-toplevel")
        raw = result.stdout.decode("utf-8", errors="replace").strip()
        if result.rc == 0 and raw:
            stop = Path(os.path.realpath(raw))
    result = []
    while True:
        result.append(current)
        if current == stop or current.parent == current:
            break
        current = current.parent
    return result


def _root_sessions(index, root: Path) -> list[list[Record]]:
    sessions = []
    for records in index.sessions().values():
        if any(record.cwd and _inside(record.cwd, root) for record in records):
            sessions.append(records)
    return sessions


def _recent_cwds(sessions: list[list[Record]], root: Path) -> list[Path]:
    def activity(records: list[Record]) -> float:
        return max((record.timestamp or 0.0 for record in records), default=0.0)

    result = []
    seen = set()
    for records in sorted(sessions, key=activity, reverse=True)[:10]:
        candidates = [
            record
            for record in records
            if record.cwd and _inside(record.cwd, root)
        ]
        if not candidates:
            continue
        cwd = Path(os.path.realpath(candidates[-1].cwd or root))
        if cwd == Path(os.path.realpath(root)) or cwd in seen:
            continue
        seen.add(cwd)
        result.append(cwd)
    return result


def _display(path: Path, root: Path, home: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        try:
            relative = path.relative_to(home)
        except ValueError:
            return str(path)
        return "~" if not relative.parts else "~/" + relative.as_posix()


def _date(value: float | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _invoked_names(record: Record, seen_tool_uses: set[str]) -> list[str]:
    # invoked_skills attachments are re-sent after compaction, so they are not invocations.
    names = []
    if record.command_name and not record.is_meta:
        names.append(record.command_name)
    for item in record.tool_uses:
        if item.name != "Skill" or not item.skill:
            continue
        if item.tool_use_id is not None:
            if item.tool_use_id in seen_tool_uses:
                continue
            seen_tool_uses.add(item.tool_use_id)
        names.append(item.skill)
    return names


def _invocations(name: str, records: list[Record]) -> tuple[dict[str, int], str | None]:
    counts = {}
    timestamps = []
    seen_tool_uses: set[str] = set()
    for record in records:
        for invoked in _invoked_names(record, seen_tool_uses):
            if invoked.rsplit(":", 1)[-1] != name:
                continue
            counts[invoked] = counts.get(invoked, 0) + 1
            if record.timestamp is not None:
                timestamps.append(record.timestamp)
    last = _date(max(timestamps)) if timestamps else None
    return counts, last


def _signature(item: SkillEntry | None) -> tuple[str, str, str] | None:
    if item is None:
        return None
    return item.qualified, item.source, os.path.realpath(item.path)


def _skill_views(
    root: Path,
    home: Path,
    recent_cwds: list[Path],
    records: list[Record],
) -> tuple[dict, dict[str, SkillEntry | None]]:
    base_entries = list_skills(home, _cwd_chain(root, home))
    entries_by_cwd = [(root, base_entries)]
    entries_by_cwd.extend(
        (cwd, list_skills(home, _cwd_chain(cwd, home))) for cwd in recent_cwds
    )
    all_entries = []
    seen = set()
    for _cwd, entries in entries_by_cwd:
        for item in entries:
            key = os.path.realpath(item.path)
            if key in seen:
                continue
            seen.add(key)
            all_entries.append(item)

    views = {}
    resolved = {}
    for name in _COMMANDS:
        item = resolve(name, base_entries)
        resolved[name] = item
        variants = {_signature(resolve(name, entries)) for _cwd, entries in entries_by_cwd}
        counts, last = _invocations(name, records)
        views[name] = {
            "resolves_to": (
                {
                    "qualified": item.qualified,
                    "source": item.source,
                    "path": _display(item.path, root, home),
                }
                if item is not None
                else None
            ),
            "also_listed_as": plugin_twins(name, all_entries),
            "invoked_window": counts,
            "last_invoked_at": last,
            "resolution_varies_by_cwd": len(variants) > 1,
        }
    return views, resolved


def _read(path: Path | None, ctx: Context) -> str:
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        ctx.error(NAME, "instruction_read")
        return ""


def _generic_target(target: str, kind: str) -> bool:
    if "/" in target or Path(target).is_absolute():
        return False
    if kind == "HANDOFF":
        return re.fullmatch(
            r"(?:HANDOFF|(?:<[^>]+>|XXX|[\w{}-]+)-HANDOFF)\.md",
            target,
            re.IGNORECASE,
        ) is not None
    if kind == "CHANGELOG":
        return re.fullmatch(
            r"(?:CHANGELOG|(?:<[^>]+>|XXX|[\w{}-]+)-CHANGELOG)\.md",
            target,
            re.IGNORECASE,
        ) is not None
    return False


def _target_display(target: str, root: Path) -> tuple[str, bool]:
    path = Path(target).expanduser()
    outside = path.is_absolute() and not _inside(path, root)
    if path.is_absolute() and _inside(path, root):
        try:
            return path.relative_to(root).as_posix(), outside
        except ValueError:
            pass
    return path.as_posix(), outside


def _write_views(
    root: Path,
    targets: list[WriteTarget],
    handoff_document: dict,
    *,
    changelog_document: dict | None = None,
    line_offset: int = 0,
) -> list[dict]:
    result = []
    for item in targets:
        document = (
            changelog_document
            if item.kind == "CHANGELOG" and changelog_document is not None
            else handoff_document
        )
        canon = document["canon"]
        canon_path = canon["path"] if canon is not None else None
        journals = [entry["glob"] for entry in document["journals"]]
        target, outside = _target_display(item.target, root)
        match = None
        if canon_path is None:
            writes_canon = None
        elif target == canon_path:
            writes_canon = True
            match = "exact"
        elif _generic_target(target, item.kind):
            writes_canon = True
            match = "generic"
        else:
            writes_canon = False
        writes_journal = any(
            target == pattern or fnmatch.fnmatchcase(target, pattern)
            for pattern in journals
        )
        result.append(
            {
                "target": target,
                "kind": item.kind,
                "line": item.line + line_offset,
                "confidence": item.confidence,
                "writes_canon": writes_canon,
                "writes_journal": writes_journal,
                "outside_root": outside,
                "match": match,
            }
        )
    return result


def _codex_writes(root: Path, handoff: dict, changelog: dict) -> list[dict]:
    path = root / "AGENTS.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    section = agents_md_close_section(text)
    if section is None:
        return []
    start = text.find(section)
    offset = text[:start].count("\n") if start >= 0 else 0
    return _write_views(
        root,
        write_targets(section),
        handoff,
        changelog_document=changelog,
        line_offset=offset,
    )


def _latest_non_git(root: Path, ctx: Context, documents: list[dict]) -> tuple[str | None, str | None]:
    values = []
    for document in documents:
        canon = document["canon"]
        if canon is not None and canon["date"] is not None:
            values.append((canon["date"], canon["date_source"]))
        for journal in document["journals"]:
            last = journal["last"]
            if last is not None and last["date"] is not None:
                values.append((last["date"], last["source"]))
    for entry in iter_files(root, ctx, NAME):
        if entry.is_symlink or entry.path.suffix.lower() not in CODE_EXTS:
            continue
        value = _date(entry.mtime)
        if value is not None:
            values.append((value, "mtime"))
    return max(values, default=(None, None), key=lambda item: item[0] or "")


def _project_active(
    root: Path,
    ctx: Context,
    vcs: bool,
    documents: list[dict],
) -> dict:
    if vcs:
        result = runner.git(
            root,
            "log",
            "-1",
            "--since=14.days",
            "--format=%ct",
            "--no-textconv",
            "--no-ext-diff",
        )
        raw = result.stdout.decode("ascii", errors="ignore").strip()
        timestamp = float(raw) if result.rc == 0 and raw.isdigit() else None
        basis = "git"
        # Uncommitted edits are work in progress too: take the newest mtime among modified tracked files.
        status = runner.git(root, "status", "--porcelain=v1", "-z", "--untracked-files=no")
        if status.rc == 0:
            for chunk in status.stdout.split(b"\x00"):
                rel = chunk[3:].decode("utf-8", "surrogateescape") if len(chunk) > 3 else ""
                try:
                    mtime = (root / rel).stat().st_mtime if rel else None
                except OSError:
                    mtime = None
                if mtime is not None and (timestamp is None or mtime > timestamp):
                    timestamp, basis = mtime, "git+worktree"
        last = _date(timestamp)
        active = timestamp is not None and timestamp >= datetime.now(timezone.utc).timestamp() - 14 * _DAY
        return {"value": active, "basis": basis, "last_change_at": last}
    latest, source = _latest_non_git(root, ctx, documents)
    cutoff = date.today().toordinal() - 14
    try:
        active = latest is not None and date.fromisoformat(latest).toordinal() >= cutoff
    except ValueError:
        active = False
    return {
        "value": active,
        "basis": "mtime" if source == "mtime" else "dated_files",
        "last_change_at": latest,
    }


def _has_kind(items: list[dict], kind: str) -> bool:
    return any(item["kind"] == kind for item in items)


def _root_view(root: Path, ctx: Context, index) -> dict:
    prefix = detect_prefix(root)
    handoff = find_canon(root, prefix, "HANDOFF")
    changelog = find_canon(root, prefix, "CHANGELOG")
    vcs = runner.is_git_repo(root)
    if not vcs:
        ctx.skip(NAME, "no_vcs", str(root))

    sessions = _root_sessions(index, root)
    records = [record for session in sessions for record in session]
    recent_cwds = _recent_cwds(sessions, root)
    skills, resolved = _skill_views(root, ctx.home, recent_cwds, records)

    close_text = _read(resolved["close"].path if resolved["close"] else None, ctx)
    accept_text = _read(resolved["accept"].path if resolved["accept"] else None, ctx)
    close_writes = _write_views(
        root,
        write_targets(close_text),
        handoff,
        changelog_document=changelog,
    )
    accept_targets = write_targets(accept_text)
    accept_writes = _write_views(
        root,
        accept_targets,
        handoff,
        changelog_document=changelog,
    )
    codex_writes = _codex_writes(root, handoff, changelog)

    if handoff["canon"] is None:
        close_writes_canon = None
    else:
        close_writes_canon = any(
            item["confidence"] == "verb_on_line" and item["writes_canon"] is True
            for item in close_writes
        )

    writers = []
    for name, items in (
        ("accept", accept_writes),
        ("close", close_writes),
        ("agents_md_codex", codex_writes),
    ):
        if _has_kind(items, "CHANGELOG"):
            writers.append(name)

    return {
        "prefix": prefix,
        "canon": handoff["canon"],
        "journals": handoff["journals"],
        "candidates": handoff["candidates"],
        "changelog": {
            "canon": changelog["canon"],
            "journals": changelog["journals"],
        },
        "project_active": _project_active(root, ctx, vcs, [handoff, changelog]),
        "vcs": vcs,
        "skills": skills,
        "close_writes": close_writes,
        "codex_close_writes": codex_writes,
        "accept_writes": accept_writes,
        "close_writes_canon": close_writes_canon,
        "changelog_written_by": writers,
    }


def collect(ctx: Context) -> dict:
    index = load_index(ctx)
    return {
        "roots": {
            str(root.resolve()): _root_view(root, ctx, index) for root in ctx.roots
        }
    }
