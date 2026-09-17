from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import time

from envaudit import COLLECTOR_VERSION, DEFINITIONS_VERSION

from .context import Context
from .redact import self_check


def build_document(
    ctx: Context,
    host: dict,
    sections: dict,
    durations: dict,
    roots: list[dict],
    flags_view: dict,
) -> dict:
    return {
        "collector_version": COLLECTOR_VERSION,
        "definitions_version": DEFINITIONS_VERSION,
        "collector": {
            "started_at": datetime.fromtimestamp(
                ctx.started_at, timezone.utc
            ).isoformat().replace("+00:00", "Z"),
            "duration_s": round(max(0.0, time.time() - ctx.started_at), 6),
            "python": platform.python_version(),
            "flags": flags_view,
            "section_order": list(sections),
            "section_durations_s": durations,
        },
        "host": host,
        "roots": roots,
        "window_days_effective": ctx.shared.get("window_days_effective"),
        "truncated": ctx.truncated,
        "exit_code": 0,
        "skipped": list(ctx.skipped),
        "errors": list(ctx.errors),
        "sections": sections,
    }


def _redacted_section(pointer: str) -> str:
    parts = pointer.split("/")
    if len(parts) > 2 and parts[1] == "sections":
        return parts[2].replace("~1", "/").replace("~0", "~")
    return "top"


def finalize(doc: dict, ctx: Context) -> tuple[dict, int]:
    clean_doc, pointers = self_check(doc)
    assert isinstance(clean_doc, dict)
    if pointers:
        sections = []
        for pointer in pointers:
            section = _redacted_section(pointer)
            if section not in sections:
                sections.append(section)
        for section in sections:
            error = {"section": section, "kind": "self_check_redaction"}
            clean_doc["errors"].append(error)
            ctx.errors.append(error)
        exit_code = 3
    elif any(error.get("kind") == "root_not_found" for error in ctx.errors):
        exit_code = 2
    else:
        exit_code = 0
    clean_doc["exit_code"] = exit_code
    return clean_doc, exit_code


def _serialize(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1)


def prepare_directory(directory: Path) -> None:
    missing = []
    current = directory
    while not current.exists():
        missing.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent

    for path in reversed(missing):
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            if not path.is_dir():
                raise
        else:
            path.chmod(0o700)

    if not directory.is_dir():
        raise NotADirectoryError(directory)
    mode = directory.stat().st_mode
    if mode & 0o222 == 0 or mode & 0o111 == 0:
        raise PermissionError(f"нет прав на запись в каталог {directory}")
    if not os.access(directory, os.W_OK | os.X_OK):
        raise PermissionError(f"нет прав на запись в каталог {directory}")


def prepare_output(output: Path | None) -> None:
    if output is None or output == Path("-"):
        return
    prepare_directory(output.parent)
    if output.is_dir():
        raise IsADirectoryError(output)
    if output.exists():
        if output.stat().st_mode & 0o222 == 0 or not os.access(output, os.W_OK):
            raise PermissionError(f"нет прав на запись в файл {output}")


def emit(doc: dict, output: Path | None) -> None:
    serialized = _serialize(doc) + "\n"
    if output is None or output == Path("-"):
        print(serialized, end="")
        return
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            stream.write(serialized)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
