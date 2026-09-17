from pathlib import Path

from envaudit.core.context import Context
from envaudit.core.transcripts import (
    CODE_EXTS,
    EDIT_TOOLS,
    Record,
    Usage,
    codex_home,
    iter_codex_sessions,
    load_index,
)


NAME = "tokens"
ORDER = 50
_DAY = 86400
_PERIODS = (14, 30)
_SOURCES = ("human", "task-notification", "peer", "loop", "unknown")
_INVOCATION_SOURCES = ("human", "task-notification", "peer", "unknown")
_CODEX_SKILLS = frozenset({"impl", "fix", "sprint-codex"})


def _usage_total() -> dict[str, int]:
    return {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}


def _add_usage(target: dict[str, int], usage: Usage) -> None:
    target["input"] += usage.input
    target["output"] += usage.output
    target["cache_creation"] += usage.cache_creation
    target["cache_read"] += usage.cache_read


def _in_period(record: Record, cutoff: float) -> bool:
    return record.timestamp is not None and record.timestamp >= cutoff


def _period(index, days: int) -> dict:
    cutoff = index.now - days * _DAY
    main_records = [
        record
        for record in index.usage_records(include_subagents=False)
        if _in_period(record, cutoff)
    ]
    all_records = index.usage_records(include_subagents=True)
    subagent_records = [
        record
        for record in all_records
        if record.is_subagent_file and _in_period(record, cutoff)
    ]

    total = _usage_total()
    by_model: dict[str, dict[str, int]] = {}
    for record in main_records:
        assert record.usage is not None
        _add_usage(total, record.usage)
        model_total = by_model.setdefault(
            record.model or "unknown", {**_usage_total(), "messages": 0}
        )
        _add_usage(model_total, record.usage)
        model_total["messages"] += 1

    subagents_total = _usage_total()
    for record in subagent_records:
        assert record.usage is not None
        _add_usage(subagents_total, record.usage)
    return {
        "total": total,
        "messages": len(main_records),
        "by_model": by_model,
        "subagents_total": subagents_total,
    }


def _source_name(origin: str | None) -> str:
    return origin if origin in _INVOCATION_SOURCES else "unknown"


def _by_source(index) -> tuple[dict[str, dict], dict[str, int], int, int]:
    source_totals = {name: 0 for name in _SOURCES}
    loop_invocations = {name: 0 for name in _INVOCATION_SOURCES}
    loop_refires = 0
    inferred_human_turns = 0
    deduplicated = {
        id(record) for record in index.usage_records(include_subagents=False)
    }

    for records in index.sessions().values():
        segment = "unknown"
        for record in records:
            if record.is_subagent_file:
                continue
            if record.type == "user" and not record.is_tool_result and not record.is_meta:
                if record.command_name == "loop":
                    segment = "loop"
                    source = _source_name(record.origin_kind)
                    if record.origin_kind is None:
                        source = "human"
                        inferred_human_turns += 1
                    loop_invocations[source] += 1
                elif record.loop_refire:
                    segment = "loop"
                    loop_refires += 1
                elif record.origin_kind is None and record.is_compact_summary:
                    pass
                elif (
                    record.origin_kind is None
                    and record.content_starts_task_notification
                ):
                    segment = "task-notification"
                elif record.origin_kind is None:
                    segment = "human"
                    inferred_human_turns += 1
                else:
                    segment = _source_name(record.origin_kind)
            if id(record) in deduplicated and record.usage is not None:
                source_totals[segment] += record.usage.cache_read

    grand_total = sum(source_totals.values())
    by_source = {
        name: {
            "cache_read": source_totals[name],
            "share": round(source_totals[name] / grand_total, 4) if grand_total else 0.0,
        }
        for name in _SOURCES
    }
    return by_source, loop_invocations, loop_refires, inferred_human_turns


def _qualifies_as_codex_skill(name: str) -> bool:
    return name.startswith("codex:") or name.rsplit(":", 1)[-1] in _CODEX_SKILLS


def _codex_share(index, codex_sessions: int) -> dict:
    cutoff = index.now - 14 * _DAY
    code_edits = 0
    other_edits = 0
    seen_edit_ids: set[str] = set()
    invocations: dict[str, int] = {}

    for record in index.records:
        if not _in_period(record, cutoff):
            continue
        if record.command_name and _qualifies_as_codex_skill(record.command_name):
            invocations[record.command_name] = invocations.get(record.command_name, 0) + 1
        for tool_use in record.tool_uses:
            if tool_use.name == "Skill" and tool_use.skill and _qualifies_as_codex_skill(tool_use.skill):
                invocations[tool_use.skill] = invocations.get(tool_use.skill, 0) + 1
            if tool_use.name not in EDIT_TOOLS:
                continue
            if tool_use.tool_use_id is not None:
                if tool_use.tool_use_id in seen_edit_ids:
                    continue
                seen_edit_ids.add(tool_use.tool_use_id)
            if tool_use.file_ext in CODE_EXTS:
                code_edits += 1
            else:
                other_edits += 1

    return {
        "claude_code_edits": code_edits,
        "claude_other_edits": other_edits,
        "codex_sessions": codex_sessions,
        "codex_skill_invocations": invocations,
    }


def _codex_total() -> dict[str, int]:
    return {
        "input": 0,
        "cached_input": 0,
        "cache_write_input": 0,
        "output": 0,
        "reasoning_output": 0,
        "total": 0,
    }


def _display_path(path: Path, home: Path) -> str:
    try:
        relative = path.relative_to(home)
    except ValueError:
        return str(path)
    return "~" if not relative.parts else f"~/{relative.as_posix()}"


def _codex(ctx: Context, now: float) -> tuple[dict, list]:
    home = codex_home(ctx.home)
    present = (home / "sessions").is_dir()
    sessions = list(iter_codex_sessions(ctx, since=now - 30 * _DAY)) if present else []
    counts = {}
    subagent_counts = {}
    totals = {}
    for days in _PERIODS:
        cutoff = now - days * _DAY
        selected = [
            session
            for session in sessions
            if session.last_activity_at is not None and session.last_activity_at >= cutoff
        ]
        normal = [session for session in selected if not session.is_subagent]
        counts[str(days)] = len(normal)
        subagent_counts[str(days)] = sum(
            1 for session in selected if session.is_subagent
        )
        total = _codex_total()
        for session in normal:
            if session.total is None:
                continue
            for key in total:
                total[key] += session.total[key]
        totals[str(days)] = total
    return (
        {
            "home": _display_path(home, ctx.home),
            "present": present,
            "sessions": counts,
            "subagent_sessions": subagent_counts,
            "totals": totals,
        },
        sessions,
    )


def collect(ctx: Context) -> dict:
    index = load_index(ctx)
    periods = {}
    for days in _PERIODS:
        key = str(days)
        if days > index.window_days:
            periods[key] = None
            ctx.skip(NAME, "not_applicable", f"window_days={index.window_days}")
        else:
            periods[key] = _period(index, days)

    by_source, loop_invocations, loop_refires, inferred_human_turns = _by_source(index)
    codex, _ = _codex(ctx, index.now)
    return {
        "window_days": index.window_days,
        "claude": {
            "files_read": index.files_read,
            "bad_lines": index.bad_lines,
            "duplicates_dropped": index.duplicates_dropped(),
            "periods": periods,
            "by_source": by_source,
            "loop_invocations": loop_invocations,
            "loop_refires": loop_refires,
            "inferred_human_turns": inferred_human_turns,
        },
        "codex": codex,
        "codex_share_14": _codex_share(index, codex["sessions"]["14"]),
    }
