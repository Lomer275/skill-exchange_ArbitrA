from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re


def iso(days_ago: float) -> str:
    value = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return value.isoformat().replace("+00:00", "Z")


def encode_cwd(path: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


def _write_jsonl(path: Path, lines: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines),
        encoding="utf-8",
    )
    return path


def write_session(
    home: Path,
    cwd: str,
    session: str,
    lines: list[dict],
    *,
    subagent_of: str | None = None,
) -> Path:
    project = home / ".claude" / "projects" / encode_cwd(cwd)
    if subagent_of is None:
        path = project / f"{session}.jsonl"
    else:
        path = project / subagent_of / "subagents" / f"{session}.jsonl"
    return _write_jsonl(path, lines)


def user_line(
    ts: str,
    *,
    text: str | None = None,
    command: str | None = None,
    origin: str | None = "human",
    cwd: str = "/p",
    tool_result: bool = False,
    meta: bool = False,
    compact: bool = False,
    entrypoint: str = "cli",
) -> dict:
    if command is not None:
        content: object = (
            f"<command-message>{command}</command-message>\n"
            f"<command-name>/{command}</command-name>\n"
            f"<command-args>{text or ''}</command-args>"
        )
    elif tool_result:
        content: object = [{"type": "tool_result", "content": text or ""}]
    else:
        content = text or ""
    result = {
        "type": "user",
        "timestamp": ts,
        "entrypoint": entrypoint,
        "cwd": cwd,
        "isMeta": meta,
        "isCompactSummary": compact,
        "message": {"content": content},
    }
    if origin is not None:
        result["origin"] = {"kind": origin}
    return result


def assistant_line(
    ts: str,
    *,
    msg_id: str,
    req_id: str,
    model: str = "claude-opus-5",
    usage: tuple[int, int, int, int] = (1, 1, 0, 0),
    tool_uses: list[dict] = (),
    cwd: str = "/p",
    sidechain: bool = False,
    entrypoint: str = "cli",
) -> dict:
    input_tokens, output_tokens, cache_creation, cache_read = usage
    return {
        "type": "assistant",
        "timestamp": ts,
        "entrypoint": entrypoint,
        "cwd": cwd,
        "isSidechain": sidechain,
        "requestId": req_id,
        "message": {
            "id": msg_id,
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            },
            "content": list(tool_uses),
        },
    }


def tool_use(
    name: str,
    *,
    id: str,
    file_path: str | None = None,
    skill: str | None = None,
    extra_input: dict | None = None,
) -> dict:
    tool_input = dict(extra_input or {})
    if file_path is not None:
        key = "notebook_path" if name == "NotebookEdit" else "file_path"
        tool_input[key] = file_path
    if skill is not None:
        tool_input["skill"] = skill
    return {"type": "tool_use", "id": id, "name": name, "input": tool_input}


def attachment_line(
    ts: str,
    *,
    type: str,
    content: str | None = None,
    rendered: list[str] | None = None,
    skill_count: int | None = None,
    skills: list[str] | None = None,
    files: list[str] | None = None,
    cwd: str = "/p",
) -> dict:
    attachment: dict = {"type": type}
    if content is not None:
        attachment["content"] = content
    if skill_count is not None:
        attachment["skillCount"] = skill_count
    if skills is not None:
        attachment["skills"] = [{"name": name} for name in skills]
    if files is not None:
        attachment["files"] = [{"type": file_type} for file_type in files]
    result = {
        "type": "attachment",
        "timestamp": ts,
        "cwd": cwd,
        "attachment": attachment,
    }
    if rendered is not None:
        result["rendered"] = [{"content": item} for item in rendered]
    return result


def write_codex_session(
    home: Path,
    session_id: str,
    started: str,
    totals: list[int],
    *,
    source: str = "cli",
    subagent: bool = False,
    codex_home: Path | None = None,
    last_activity: str | None = None,
) -> Path:
    root = codex_home or home / ".codex"
    parsed = datetime.fromisoformat(started.replace("Z", "+00:00"))
    path = (
        root
        / "sessions"
        / f"{parsed.year:04d}"
        / f"{parsed.month:02d}"
        / f"{parsed.day:02d}"
        / f"rollout-{session_id}.jsonl"
    )
    meta = {
        "type": "session_meta",
        "payload": {"id": session_id, "timestamp": started, "source": source},
    }
    if subagent:
        meta["payload"]["thread_source"] = "subagent"
    lines = [meta]
    for total in totals:
        line = {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": total,
                        "cached_input_tokens": 0,
                        "cache_write_input_tokens": 0,
                        "output_tokens": 0,
                        "reasoning_output_tokens": 0,
                        "total_tokens": total,
                    }
                },
            },
        }
        if last_activity is not None:
            line["timestamp"] = last_activity
        lines.append(line)
    return _write_jsonl(path, lines)


def write_settings(home: Path, data: dict) -> None:
    path = home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_claude_json(home: Path, data: dict) -> None:
    (home / ".claude.json").write_text(json.dumps(data), encoding="utf-8")
