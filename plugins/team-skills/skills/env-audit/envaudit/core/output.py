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


def emit(doc: dict, output: Path | None) -> None:
    serialized = _serialize(doc) + "\n"
    if output is None:
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
