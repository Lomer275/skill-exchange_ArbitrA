from collections import Counter
from datetime import datetime, timezone
import os
from pathlib import Path
from statistics import median

from envaudit.core import runner
from envaudit.core.constants import MEMORY_INDEX_MAX_BYTES
from envaudit.core.context import Context
from envaudit.core.skills_index import memory_dir_name
from envaudit.core.transcripts import Record, load_index
from envaudit.core.walk import iter_files


NAME = "instructions"
ORDER = 20

_PROJECT_FILES = {
    "CLAUDE.md": "claude_md",
    "AGENTS.md": "agents_md",
    "CLAUDE.local.md": "claude_local_md",
}
_INDEX_MAX_LINES = 200


def _display(path: Path, home: Path) -> str:
    try:
        relative = path.relative_to(home)
    except ValueError:
        return str(path)
    return "~" if not relative.parts else f"~/{relative.as_posix()}"


def _file_metrics(path: Path) -> tuple[bool, int, int, int]:
    try:
        raw = path.read_bytes()
    except OSError:
        return False, 0, 0, 0
    return (
        True,
        len(raw),
        len(raw.splitlines()),
        raw.count(b"BEGIN team-context"),
    )


def _global_file(path: Path, home: Path) -> dict:
    exists, size, lines, blocks = _file_metrics(path)
    return {
        "path": _display(path, home),
        "exists": exists,
        "bytes": size,
        "lines": lines,
        "team_context_blocks": blocks,
    }


def _project_files(root: Path, ctx: Context) -> dict:
    files = []
    total = 0
    for entry in iter_files(root, ctx, NAME, max_depth=3):
        kind = _PROJECT_FILES.get(entry.path.name)
        if kind is None or entry.is_symlink:
            continue
        try:
            lines = len(entry.path.read_bytes().splitlines())
        except OSError:
            ctx.skip(NAME, "permission", entry.rel)
            continue
        files.append(
            {
                "rel": entry.rel,
                "kind": kind,
                "bytes": entry.size,
                "lines": lines,
            }
        )
        total += entry.size
    return {"files": sorted(files, key=lambda item: item["rel"]), "total_bytes": total}


def _inside(path: Path | str, root: Path | str) -> bool:
    try:
        real_root = os.path.realpath(root)
        return os.path.commonpath((os.path.realpath(path), real_root)) == real_root
    except (OSError, ValueError):
        return False


def _worktrees(root: Path) -> list[Path]:
    if not runner.is_git_repo(root):
        return []
    result = runner.git(root, "worktree", "list", "--porcelain")
    if result.rc != 0:
        return []
    paths = []
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        marker, separator, raw = line.partition(" ")
        if marker == "worktree" and separator and raw:
            paths.append(Path(os.path.realpath(raw)))
    return paths


def _candidate(
    target: Path,
    matched_by: str,
    root: Path,
) -> tuple[str, str, Path]:
    encoded = memory_dir_name(str(target))
    return encoded, "prefix" if len(encoded) > 200 else matched_by, root


def _memory_candidates(ctx: Context, records: list[Record]) -> list[tuple[str, str, Path]]:
    candidates = []
    seen = set()
    for root in ctx.roots:
        additions = [_candidate(root, "root", root)]
        additions.extend(
            _candidate(path, "worktree", root)
            for path in _worktrees(root)
            if os.path.realpath(path) != os.path.realpath(root)
        )
        cwd_paths = sorted(
            {
                os.path.realpath(record.cwd)
                for record in records
                if record.cwd and _inside(record.cwd, root)
            }
        )
        additions.extend(_candidate(Path(path), "cwd", root) for path in cwd_paths)
        for encoded, matched_by, owner in additions:
            key = (encoded, str(owner))
            if key not in seen:
                candidates.append((encoded, matched_by, owner))
                seen.add(key)
    return candidates


def _memory_stats(directory: Path, root: Path, matched_by: str) -> dict:
    memory = directory / "memory"
    try:
        cards = sum(
            path.is_file() and path.name != "MEMORY.md"
            for path in memory.glob("*.md")
        )
    except OSError:
        cards = 0
    index = memory / "MEMORY.md"
    index_exists = index.is_file()
    try:
        raw = index.read_bytes()
    except OSError:
        raw = None
    lines = len(raw.splitlines()) if raw is not None else 0
    size = len(raw) if raw is not None else 0
    return {
        "name": directory.name,
        "root": str(root),
        "matched_by": matched_by,
        "cards": cards,
        "index_exists": index_exists,
        "index_lines": lines,
        "index_bytes": size,
        "index_over_lines": lines > _INDEX_MAX_LINES,
        "index_over_bytes": size > MEMORY_INDEX_MAX_BYTES,
    }


def _memory_dir_collisions(ctx: Context) -> list[dict]:
    grouped: dict[str, set[str]] = {}
    for root in ctx.roots:
        resolved = str(Path(os.path.realpath(root)))
        grouped.setdefault(memory_dir_name(resolved), set()).add(resolved)

    base = ctx.home / ".claude" / "projects"
    return [
        {
            "encoded": encoded,
            "roots": sorted(roots),
            "memory_exists": (base / encoded / "memory").is_dir(),
        }
        for encoded, roots in sorted(grouped.items())
        if len(roots) >= 2
    ]


def _memory(ctx: Context, records: list[Record]) -> dict:
    base = ctx.home / ".claude" / "projects"
    try:
        directories = sorted(
            (
                path
                for path in base.iterdir()
                if path.is_dir() and (path / "memory").is_dir()
            ),
            key=lambda path: path.name,
        )
    except OSError:
        directories = []

    candidates = _memory_candidates(ctx, records)
    mapped = []
    unmapped = []
    by_root: dict[str, list[str]] = {}
    for directory in directories:
        match = None
        for encoded, matched_by, root in candidates:
            if directory.name == encoded or (
                matched_by == "prefix" and directory.name.startswith(encoded[:200])
            ):
                match = (root, matched_by)
                break
        if match is None:
            unmapped.append(directory.name)
            continue
        root, matched_by = match
        item = _memory_stats(directory, root, matched_by)
        mapped.append(item)
        if item["cards"] or item["index_bytes"]:
            by_root.setdefault(str(root), []).append(directory.name)

    return {
        "dirs": mapped,
        "unmapped_memory_dirs": unmapped,
        "roots_with_multiple_dirs": {
            root: sorted(names)
            for root, names in sorted(by_root.items())
            if len(names) >= 2
        },
    }


def _session_root(records: list[Record], root: Path) -> tuple[Record, float] | None:
    main = [record for record in records if not record.is_subagent_file]
    first_user = next((record for record in main if record.type == "user"), None)
    if first_user is None or first_user.cwd is None or not _inside(first_user.cwd, root):
        return None
    first_timestamp = next(
        (record.timestamp for record in main if record.timestamp is not None), 0.0
    )
    return first_user, first_timestamp


def _last_instructions(sessions: list[list[Record]]) -> dict | None:
    candidates = [
        record
        for records in sessions
        for record in records
        if not record.is_subagent_file
        and record.attachment_type == "instructions"
        and record.attachment_len is not None
    ]
    if not candidates:
        return None
    record = max(candidates, key=lambda item: (item.timestamp or 0.0, item.line_no))
    file_types = Counter(record.instruction_file_types)
    return {
        "length": record.attachment_len,
        "file_types": dict(sorted(file_types.items())),
        "date": datetime.fromtimestamp(record.timestamp, timezone.utc).date().isoformat()
        if record.timestamp is not None
        else None,
    }


def _start_context(root: Path, index) -> dict:
    sessions = []
    for records in index.sessions().values():
        main = [record for record in records if not record.is_subagent_file]
        numbered = [
            record
            for record in main
            if isinstance(record.line_no, int) and record.line_no > 0
        ]
        first_record = (
            min(numbered, key=lambda record: record.line_no)
            if numbered
            else (main[0] if main else None)
        )
        match = _session_root(records, root)
        if match is not None and first_record is not None:
            first_user, first_timestamp = match
            sessions.append((first_timestamp, records, first_user, first_record))
        elif (
            first_record is not None
            and numbered
            and first_record.line_no != 1
            and first_record.cwd is not None
            and _inside(first_record.cwd, root)
        ):
            sessions.append(
                (first_record.timestamp or 0.0, records, None, first_record)
            )
    all_root_sessions = [records for _, records, _, _ in sessions]
    selected = sorted(sessions, key=lambda item: item[0])[-40:]
    excluded = 0
    excluded_started_before_window = 0
    history_marked = 0
    values: dict[str, list[int]] = {}
    fresh_values: dict[str, list[int]] = {}
    for _timestamp, records, first_user, first_record in selected:
        if numbered_line := (
            first_record.line_no
            if isinstance(first_record.line_no, int) and first_record.line_no > 0
            else None
        ):
            if numbered_line != 1:
                excluded_started_before_window += 1
                continue
        first_content_user = next(
            (
                record
                for record in records
                if not record.is_subagent_file
                and record.type == "user"
                and not record.is_meta
                and not record.is_tool_result
            ),
            None,
        )
        is_history = first_record.has_parent or (
            first_content_user is not None
            and first_content_user.is_compact_summary
        )
        if is_history:
            history_marked += 1
        answer = next(
            (
                record
                for record in records
                if not record.is_subagent_file
                and record.type == "assistant"
                and record.usage is not None
                and not record.is_sidechain
                and record.model != "<synthetic>"
            ),
            None,
        )
        if answer is None:
            excluded += 1
            continue
        usage = answer.usage
        assert usage is not None
        total = usage.input + usage.cache_creation + usage.cache_read
        entrypoint = first_record.entrypoint or (
            first_user.entrypoint if first_user is not None else None
        )
        values.setdefault(entrypoint or "unknown", []).append(total)
        if not is_history:
            fresh_values.setdefault(entrypoint or "unknown", []).append(total)

    by_entrypoint = {
        entrypoint: {
            "n": len(numbers),
            "median": median(numbers),
            "min": min(numbers),
            "max": max(numbers),
        }
        for entrypoint, numbers in sorted(values.items())
    }
    by_entrypoint_fresh = {
        entrypoint: {
            "n": len(numbers),
            "median": median(numbers),
            "min": min(numbers),
            "max": max(numbers),
        }
        for entrypoint, numbers in sorted(fresh_values.items())
    }
    return {
        "sessions_considered": len(selected),
        "excluded": excluded,
        "excluded_started_before_window": excluded_started_before_window,
        "history_marked": history_marked,
        "by_entrypoint": by_entrypoint,
        "by_entrypoint_fresh": by_entrypoint_fresh,
        "last_instructions": _last_instructions(all_root_sessions),
    }


def collect(ctx: Context) -> dict:
    index = load_index(ctx)
    host = ctx.shared.get("host")
    raw_codex_home = host.get("codex_home") if isinstance(host, dict) else None
    codex_home = (
        Path(raw_codex_home)
        if isinstance(raw_codex_home, str)
        else ctx.home / ".codex"
    )
    return {
        "global": {
            "claude_md": _global_file(ctx.home / ".claude" / "CLAUDE.md", ctx.home),
            "codex_agents_md": _global_file(codex_home / "AGENTS.md", ctx.home),
        },
        "projects": {str(root): _project_files(root, ctx) for root in ctx.roots},
        "memory_dir_collisions": _memory_dir_collisions(ctx),
        "memory": _memory(ctx, index.records),
        "start_context": {
            str(root): _start_context(root, index) for root in ctx.roots
        },
    }
