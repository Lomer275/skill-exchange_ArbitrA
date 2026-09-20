from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time

from .context import Context
from .walk import FileEntry, iter_files


CODE_EXTS = frozenset({".py", ".js", ".ts", ".php", ".sh", ".sql", ".cs", ".ps1"})
EDIT_TOOLS = frozenset({"Edit", "MultiEdit", "Write", "NotebookEdit"})

# Container paths are included because projecting a leaf necessarily reads its parent.
WHITELIST_PATHS: tuple[str, ...] = (
    "type",
    "timestamp",
    "entrypoint",
    "cwd",
    "isSidechain",
    "isMeta",
    "isCompactSummary",
    "parentUuid",
    "origin",
    "origin.kind",
    "requestId",
    "message",
    "message.id",
    "message.model",
    "message.usage",
    "message.usage.input_tokens",
    "message.usage.output_tokens",
    "message.usage.cache_creation_input_tokens",
    "message.usage.cache_read_input_tokens",
    "message.content",
    "message.content[]",
    "message.content[].type",
    "message.content[].id",
    "message.content[].name",
    "message.content[].input",
    "message.content[].input.skill",
    "message.content[].input.file_path",
    "message.content[].input.notebook_path",
    "attachment",
    "attachment.type",
    "attachment.skillCount",
    "attachment.skills",
    "attachment.skills[]",
    "attachment.skills[].name",
    "attachment.files",
    "attachment.files[]",
    "attachment.files[].type",
    "attachment.content",
    "rendered",
    "rendered[]",
    "rendered[].content",
    "payload",
    "payload.type",
    "payload.id",
    "payload.timestamp",
    "payload.source",
    "payload.thread_source",
    "payload.info",
    "payload.info.total_token_usage",
    "payload.info.total_token_usage.input_tokens",
    "payload.info.total_token_usage.cached_input_tokens",
    "payload.info.total_token_usage.cache_write_input_tokens",
    "payload.info.total_token_usage.output_tokens",
    "payload.info.total_token_usage.reasoning_output_tokens",
    "payload.info.total_token_usage.total_tokens",
)

_COMMAND_RE = re.compile(r"<command-name>/?([\w:.-]+)</command-name>")
_DAY = 86400


@dataclass(frozen=True)
class Usage:
    input: int
    output: int
    cache_creation: int
    cache_read: int


@dataclass(frozen=True)
class ToolUse:
    tool_use_id: str | None
    name: str
    skill: str | None
    file_ext: str | None


@dataclass(frozen=True)
class Record:
    project_dir: str
    session: str
    is_subagent_file: bool
    line_no: int
    type: str | None
    timestamp: float | None
    entrypoint: str | None
    cwd: str | None
    is_sidechain: bool
    is_meta: bool
    is_compact_summary: bool
    has_parent: bool
    origin_kind: str | None
    is_tool_result: bool
    message_id: str | None
    request_id: str | None
    model: str | None
    usage: Usage | None
    tool_uses: tuple[ToolUse, ...]
    command_name: str | None
    loop_refire: bool
    content_starts_task_notification: bool
    attachment_type: str | None
    attachment_len: int | None
    skill_count: int | None
    invoked_skill_names: tuple[str, ...]
    instruction_file_types: tuple[str, ...]


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _integer(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _mapping(value: object) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _timestamp(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _usage(message: Mapping) -> Usage | None:
    raw = message.get("usage")
    if not isinstance(raw, Mapping):
        return None
    return Usage(
        input=_integer(raw.get("input_tokens")),
        output=_integer(raw.get("output_tokens")),
        cache_creation=_integer(raw.get("cache_creation_input_tokens")),
        cache_read=_integer(raw.get("cache_read_input_tokens")),
    )


def _content_projection(
    content: object,
) -> tuple[tuple[ToolUse, ...], bool, str | None, bool, bool]:
    if isinstance(content, str):
        match = _COMMAND_RE.search(content)
        return (
            (),
            False,
            match.group(1) if match else None,
            "<<autonomous-loop" in content or "ScheduleWakeup" in content,
            content.startswith("<task-notification>"),
        )
    if not isinstance(content, list):
        return (), False, None, False, False

    tool_uses = []
    is_tool_result = False
    for item in content:
        if not isinstance(item, Mapping):
            continue
        item_type = _string(item.get("type"))
        if item_type == "tool_result":
            is_tool_result = True
            continue
        if item_type != "tool_use":
            continue
        tool_input = _mapping(item.get("input"))
        file_path = _string(tool_input.get("file_path"))
        if file_path is None:
            file_path = _string(tool_input.get("notebook_path"))
        tool_uses.append(
            ToolUse(
                tool_use_id=_string(item.get("id")),
                name=_string(item.get("name")) or "",
                skill=_string(tool_input.get("skill")),
                file_ext=os.path.splitext(file_path)[1].lower() if file_path else None,
            )
        )
    return tuple(tool_uses), is_tool_result, None, False, False


def _attachment_projection(
    obj: Mapping,
) -> tuple[str | None, int | None, int | None, tuple[str, ...], tuple[str, ...]]:
    attachment = _mapping(obj.get("attachment"))
    attachment_type = _string(attachment.get("type"))

    lengths = []
    content = attachment.get("content")
    if isinstance(content, str):
        lengths.append(len(content))
    rendered = obj.get("rendered")
    if isinstance(rendered, list):
        for item in rendered:
            if not isinstance(item, Mapping):
                continue
            rendered_content = item.get("content")
            if isinstance(rendered_content, str):
                lengths.append(len(rendered_content))

    raw_skill_count = attachment.get("skillCount")
    skill_count = (
        raw_skill_count
        if isinstance(raw_skill_count, int) and not isinstance(raw_skill_count, bool)
        else None
    )

    names = []
    skills = attachment.get("skills")
    if isinstance(skills, list):
        for item in skills:
            if isinstance(item, Mapping):
                name = _string(item.get("name"))
                if name is not None:
                    names.append(name)

    file_types = []
    files = attachment.get("files")
    if isinstance(files, list):
        for item in files:
            if isinstance(item, Mapping):
                file_type = _string(item.get("type"))
                if file_type is not None:
                    file_types.append(file_type)

    return (
        attachment_type,
        sum(lengths) if lengths else None,
        skill_count,
        tuple(names),
        tuple(file_types),
    )


def project_line(
    obj: Mapping,
    *,
    project_dir: str,
    session: str,
    is_subagent_file: bool,
    line_no: int,
) -> Record | None:
    message = _mapping(obj.get("message"))
    origin = _mapping(obj.get("origin"))
    (
        tool_uses,
        is_tool_result,
        command_name,
        loop_refire,
        content_starts_task_notification,
    ) = _content_projection(message.get("content"))
    (
        attachment_type,
        attachment_len,
        skill_count,
        invoked_skill_names,
        instruction_file_types,
    ) = _attachment_projection(obj)
    return Record(
        project_dir=project_dir,
        session=session,
        is_subagent_file=is_subagent_file,
        line_no=line_no,
        type=_string(obj.get("type")),
        timestamp=_timestamp(obj.get("timestamp")),
        entrypoint=_string(obj.get("entrypoint")),
        cwd=_string(obj.get("cwd")),
        is_sidechain=obj.get("isSidechain") is True,
        is_meta=obj.get("isMeta") is True,
        is_compact_summary=obj.get("isCompactSummary") is True,
        has_parent=obj.get("parentUuid") is not None,
        origin_kind=_string(origin.get("kind")),
        is_tool_result=is_tool_result,
        message_id=_string(message.get("id")),
        request_id=_string(obj.get("requestId")),
        model=_string(message.get("model")),
        usage=_usage(message),
        tool_uses=tool_uses,
        command_name=command_name,
        loop_refire=loop_refire,
        content_starts_task_notification=content_starts_task_notification,
        attachment_type=attachment_type,
        attachment_len=attachment_len,
        skill_count=skill_count,
        invoked_skill_names=invoked_skill_names,
        instruction_file_types=instruction_file_types,
    )


def window_days_effective(home: Path) -> int:
    try:
        raw = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 30
    if not isinstance(raw, Mapping):
        return 30
    days = raw.get("cleanupPeriodDays")
    if isinstance(days, int) and not isinstance(days, bool) and days > 0:
        return days
    return 30


@dataclass
class TranscriptIndex:
    window_days: int
    since: float
    now: float
    records: list[Record]
    files_read: int
    bad_lines: int

    def usage_records(self, *, include_subagents: bool) -> list[Record]:
        result = []
        seen: set[tuple[str | None, str | None]] = set()
        for record in self.records:
            if record.type != "assistant" or record.usage is None:
                continue
            if record.is_subagent_file and not include_subagents:
                continue
            key = (record.message_id, record.request_id)
            if key != (None, None):
                if key in seen:
                    continue
                seen.add(key)
            result.append(record)
        return result

    def duplicates_dropped(self) -> int:
        candidates = [
            record
            for record in self.records
            if record.type == "assistant" and record.usage is not None
        ]
        return len(candidates) - len(self.usage_records(include_subagents=True))

    def sessions(self) -> dict[tuple[str, str], list[Record]]:
        grouped: dict[tuple[str, str], list[Record]] = {}
        for record in self.records:
            grouped.setdefault((record.project_dir, record.session), []).append(record)
        for records in grouped.values():
            records.sort(key=lambda item: item.line_no)
        return grouped


def _claude_file(entry: FileEntry) -> tuple[str, str, bool] | None:
    parts = Path(entry.rel).parts
    if len(parts) == 2 and parts[1].endswith(".jsonl"):
        return parts[0], Path(parts[1]).stem, False
    if (
        len(parts) == 4
        and parts[2] == "subagents"
        and parts[3].endswith(".jsonl")
    ):
        return parts[0], parts[1], True
    return None


def load_index(ctx: Context) -> TranscriptIndex:
    cached = ctx.shared.get("transcripts")
    if isinstance(cached, TranscriptIndex):
        return cached

    build_started = time.perf_counter()
    try:
        return _build_index(ctx)
    finally:
        elapsed = time.perf_counter() - build_started
        previous = ctx.shared.get("index_build_seconds", 0.0)
        if not isinstance(previous, (int, float)):
            previous = 0.0
        ctx.shared["index_build_seconds"] = previous + elapsed


def _build_index(ctx: Context) -> TranscriptIndex:
    window_days = window_days_effective(ctx.home)
    now = time.time()
    since = now - window_days * _DAY
    records: list[Record] = []
    files_read = 0
    bad_lines = 0
    projects = ctx.home / ".claude" / "projects"
    entries = []
    if projects.is_dir():
        entries = sorted(
            iter_files(projects, ctx, "tokens", max_depth=3),
            key=lambda item: item.rel,
        )
    for entry in entries:
        location = _claude_file(entry)
        if location is None or entry.is_symlink or entry.mtime < since - _DAY:
            continue
        if ctx.expired():
            ctx.mark_truncated()
            break
        project_dir, session, is_subagent_file = location
        try:
            stream = entry.path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            ctx.error("tokens", "transcript_read")
            continue
        files_read += 1
        with stream:
            for line_no, line in enumerate(stream, 1):
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    bad_lines += 1
                    continue
                if not isinstance(obj, Mapping):
                    continue
                record = project_line(
                    obj,
                    project_dir=project_dir,
                    session=session,
                    is_subagent_file=is_subagent_file,
                    line_no=line_no,
                )
                if record is not None and (
                    record.timestamp is None or record.timestamp >= since
                ):
                    records.append(record)

    index = TranscriptIndex(window_days, since, now, records, files_read, bad_lines)
    ctx.shared["transcripts"] = index
    ctx.shared["window_days_effective"] = window_days
    return index


def skill_usage(home: Path) -> dict[str, dict]:
    try:
        raw = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, Mapping):
        return {}
    usage = raw.get("skillUsage")
    if not isinstance(usage, Mapping):
        return {}

    result = {}
    for name, item in usage.items():
        if not isinstance(name, str) or not isinstance(item, Mapping):
            continue
        count = item.get("usageCount")
        used_at = item.get("lastUsedAt")
        result[name] = {
            "usage_count": _integer(count),
            "last_used_at": (
                used_at / 1000.0
                if isinstance(used_at, (int, float)) and not isinstance(used_at, bool)
                else None
            ),
        }
    return result


@dataclass(frozen=True)
class CodexSession:
    path_rel: str
    session_id: str | None
    started_at: float | None
    last_activity_at: float | None
    source_kind: str | None
    is_subagent: bool
    total: dict[str, int] | None


def codex_home(home: Path) -> Path:
    configured = Path(os.environ.get("CODEX_HOME", str(home / ".codex"))).expanduser()
    return Path(os.path.realpath(configured))


def _codex_total(raw: Mapping) -> dict[str, int]:
    return {
        "input": _integer(raw.get("input_tokens")),
        "cached_input": _integer(raw.get("cached_input_tokens")),
        "cache_write_input": _integer(raw.get("cache_write_input_tokens")),
        "output": _integer(raw.get("output_tokens")),
        "reasoning_output": _integer(raw.get("reasoning_output_tokens")),
        "total": _integer(raw.get("total_tokens")),
    }


def _codex_line(
    obj: Mapping,
) -> tuple[str, str | None, float | None, str | None, bool, dict[str, int] | None]:
    record_type = _string(obj.get("type")) or ""
    payload = _mapping(obj.get("payload"))
    if record_type == "session_meta":
        source = _string(payload.get("source"))
        thread_source = _string(payload.get("thread_source"))
        is_subagent = thread_source == "subagent" or (
            source is not None and "subagent" in source.lower()
        )
        return (
            record_type,
            _string(payload.get("id")),
            _timestamp(payload.get("timestamp")),
            source,
            is_subagent,
            None,
        )
    if record_type == "event_msg" and _string(payload.get("type")) == "token_count":
        info = _mapping(payload.get("info"))
        total_usage = info.get("total_token_usage")
        if isinstance(total_usage, Mapping):
            return record_type, None, None, None, False, _codex_total(total_usage)
    return record_type, None, None, None, False, None


def iter_codex_sessions(ctx: Context, *, since: float) -> Iterator[CodexSession]:
    home = codex_home(ctx.home)
    sessions = home / "sessions"
    if not sessions.is_dir():
        return
    entries = sorted(iter_files(sessions, ctx, "tokens"), key=lambda item: item.rel)
    for entry in entries:
        if (
            entry.is_symlink
            or not entry.path.name.startswith("rollout-")
            or entry.path.suffix != ".jsonl"
            or entry.mtime < since - _DAY
        ):
            continue
        if ctx.expired():
            ctx.mark_truncated()
            return
        session_id = None
        started_at = None
        last_activity_at = None
        source_kind = None
        is_subagent = False
        best_total = None
        try:
            stream = entry.path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            ctx.error("tokens", "codex_session_read")
            continue
        with stream:
            for line in stream:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, Mapping):
                    continue
                activity_at = _timestamp(obj.get("timestamp"))
                if activity_at is None:
                    activity_at = _timestamp(_mapping(obj.get("payload")).get("timestamp"))
                if activity_at is not None and (
                    last_activity_at is None or activity_at > last_activity_at
                ):
                    last_activity_at = activity_at
                kind, found_id, found_at, found_source, found_subagent, total = _codex_line(obj)
                if kind == "session_meta":
                    session_id = found_id
                    started_at = found_at
                    source_kind = found_source
                    is_subagent = found_subagent
                elif total is not None and (
                    best_total is None or total["total"] >= best_total["total"]
                ):
                    best_total = total
        yield CodexSession(
            path_rel=entry.path.relative_to(home).as_posix(),
            session_id=session_id,
            started_at=started_at,
            last_activity_at=(
                last_activity_at if last_activity_at is not None else entry.mtime
            ),
            source_kind=source_kind,
            is_subagent=is_subagent,
            total=best_total,
        )
