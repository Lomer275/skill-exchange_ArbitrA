from datetime import datetime
import os
from pathlib import Path
import re

from envaudit.reality import snapshot
from envaudit.reality.sandbox import read_json, write_json


_EVIDENCE = re.compile(r"опечат|readme|t999", re.IGNORECASE)
_NOTHING = re.compile(r"нечего фиксировать|nothing to record|фиксировать нечего", re.IGNORECASE)
OUTSIDE_IGNORE = (
    "/tmp/claude-*",
    "~/.claude/skills/synced/**",
    "~/.claude/statsig/**",
    "~/.claude/*.log",
    "~/.claude/history.jsonl",
    "~/.claude/__store.db*",
    "~/.claude/shell-snapshots/**",
)
_WINDOW_GRACE_SECONDS = 5.0


def _started(document: dict, run_document: dict | None) -> float:
    if run_document is not None and isinstance(run_document.get("started_at"), (int, float)):
        return float(run_document["started_at"])
    raw = document.get("created_at")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return 0.0


def _display_outside(path: str) -> str:
    home = os.path.abspath(os.fspath(Path.home()))
    absolute = os.path.abspath(path)
    try:
        relative = Path(absolute).relative_to(home)
    except ValueError:
        return snapshot.safe_path(absolute)[0]
    value = "~" if not relative.parts else "~/" + relative.as_posix()
    return snapshot.safe_path(value)[0]


def _display_sandbox(changes: dict, sandbox_dir: Path) -> dict:
    result = {}
    for kind, paths in changes.items():
        values = []
        for raw in paths:
            try:
                value = Path(raw).relative_to(sandbox_dir).as_posix()
            except ValueError:
                value = str(raw)
            values.append(snapshot.safe_path(value)[0])
        result[kind] = sorted(values)
    return result


def _display_changes(changes: dict) -> dict:
    result = {"created": [], "modified": [], "deleted": []}
    for kind, paths in changes.items():
        for path in paths:
            result[kind].append(_display_outside(path))
        result[kind].sort()
    return result


def _run_window(run_document: dict | None) -> tuple[float, float] | None:
    if run_document is None:
        return None
    started = run_document.get("started_at")
    finished = run_document.get("finished_at")
    if (
        not isinstance(started, (int, float))
        or isinstance(started, bool)
        or not isinstance(finished, (int, float))
        or isinstance(finished, bool)
        or finished < started
    ):
        return None
    return float(started), float(finished) + _WINDOW_GRACE_SECONDS


def _partition_outside_changes(
    changes: dict,
    after: dict,
    run_document: dict | None,
) -> tuple[dict, list[str]]:
    if run_document is None:
        return changes, []

    in_window = {"created": [], "modified": [], "deleted": []}
    out_of_window = []
    window = _run_window(run_document)
    for kind, paths in changes.items():
        for path in paths:
            included = kind == "deleted" and window is not None
            if kind in ("created", "modified") and window is not None:
                value = after.get(path, {})
                mtime = value.get("mtime")
                included = (
                    isinstance(mtime, (int, float))
                    and not isinstance(mtime, bool)
                    and window[0] <= float(mtime) <= window[1]
                )
            if included:
                in_window[kind].append(path)
            else:
                out_of_window.append(_display_outside(path))
        in_window[kind].sort()
    return in_window, sorted(set(out_of_window))


def _ignored_outside(path: str) -> bool:
    absolute = Path(os.path.abspath(path))
    for raw_pattern in OUTSIDE_IGNORE:
        expanded = os.path.abspath(os.path.expanduser(raw_pattern))
        if expanded.endswith("/**"):
            expanded = expanded[:-3]
        if any(candidate.match(expanded) for candidate in (absolute, *absolute.parents)):
            return True
    return False


def _outside_for_verdict(changes: dict) -> dict:
    return {
        kind: sorted(path for path in paths if not _ignored_outside(path))
        for kind, paths in changes.items()
    }


def _flatten(changes: dict) -> list[str]:
    return sorted({path for paths in changes.values() for path in paths})


def _reason(run_document: dict | None) -> str:
    if run_document is None:
        return "no_run"
    subtype = run_document.get("subtype")
    if subtype == "error_max_turns":
        return "max_turns"
    if subtype == "error_max_budget_usd":
        return "max_budget"
    if run_document.get("permission_denials_count", 0) > 0:
        return "permission_denied"
    text = run_document.get("result_text")
    if isinstance(text, str) and _NOTHING.search(text):
        return "nothing_to_record"
    return "unknown"


def _changed_canon(canon: str | None, changes: dict, sandbox_dir: Path) -> bool:
    if canon is None:
        return False
    try:
        relative = Path(canon).relative_to(sandbox_dir).as_posix()
    except ValueError:
        return False
    if relative not in changes["created"] + changes["modified"]:
        return False
    try:
        text = Path(canon).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _EVIDENCE.search(text) is not None


def _other_writes(kind: str, canon: str | None, changes: dict, sandbox_dir: Path) -> list[str]:
    canon_rel = None
    if canon is not None:
        try:
            canon_rel = Path(canon).relative_to(sandbox_dir).as_posix()
        except ValueError:
            pass
    marker = kind.upper()
    return sorted(
        path
        for path in changes["created"] + changes["modified"]
        if marker in Path(path).name.upper() and path != canon_rel
    )


def _document_verdict(
    kind: str,
    canon: str | None,
    changes: dict,
    outside: dict,
    sandbox_dir: Path,
    run_document: dict | None,
    *,
    no_changelog_path: bool = False,
    snapshot_truncated: bool = False,
) -> dict:
    if run_document is None:
        return {"status": "not_checked", "reason": "no_run"}
    if snapshot_truncated:
        return {"status": "not_checked", "reason": "snapshot_truncated"}
    outside_paths = _flatten(outside)
    if outside_paths:
        return {"status": "not_isolated", "paths": outside_paths}
    if _changed_canon(canon, changes, sandbox_dir):
        return {"status": "works"}
    written_to = _other_writes(kind, canon, changes, sandbox_dir)
    if written_to:
        return {"status": "not_working", "written_to": written_to}
    if no_changelog_path:
        return {"status": "not_checked", "reason": "no_changelog_path"}
    return {"status": "not_checked", "reason": _reason(run_document)}


def _run_view(run_document: dict | None) -> dict | None:
    if run_document is None:
        return None
    keys = (
        "started_at",
        "finished_at",
        "rc",
        "timed_out",
        "parse_error",
        "subtype",
        "is_error",
        "num_turns",
        "total_cost_usd",
        "permission_denials_count",
    )
    return {key: run_document[key] for key in keys if key in run_document}


def _typo_fixed(document: dict) -> bool:
    readme = Path(document["sandbox"]) / "README.md"
    try:
        text = readme.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    original = document.get("typo_line")
    expected = str(original).replace("опечаткаа", "опечатка")
    return isinstance(original, str) and original not in text and expected in text


def build_verdict(sandbox_file: Path, run_file: Path | None = None) -> dict:
    document = read_json(sandbox_file)
    before = read_json(sandbox_file.parent / "snapshot_before.json")
    selected_run = run_file or sandbox_file.parent / "run.json"
    run_document = read_json(selected_run) if selected_run.exists() else None
    run_started = _started(document, run_document)
    sandbox_dir = Path(document["sandbox"])
    owned = [Path(path) for path in document.get("owned_paths", []) if isinstance(path, str)]
    scan = snapshot.ScanState()
    before_truncated = bool(
        document.get("snapshot_truncated") or before.get("snapshot_truncated")
    )
    if before_truncated:
        scan.truncated = True
        after_outside = {}
        after_sandbox = {}
    else:
        after_outside = snapshot.take(
            snapshot.expand_targets(),
            exclude=owned,
            state=scan,
        )
        after_sandbox = snapshot.take([sandbox_dir], exclude=[], state=scan)
    snapshot_truncated = before_truncated or scan.truncated
    if snapshot_truncated:
        outside_raw = {"created": [], "modified": [], "deleted": []}
        sandbox_raw = {"created": [], "modified": [], "deleted": []}
    else:
        outside_raw = snapshot.diff(
            before.get("outside", {}),
            after_outside,
            run_started=None,
        )
        sandbox_raw = snapshot.diff(
            before.get("sandbox", {}),
            after_sandbox,
            run_started=run_started,
        )
    outside_in_window, outside_changes_out_of_window = _partition_outside_changes(
        outside_raw,
        after_outside,
        run_document,
    )
    outside_changes = _display_changes(outside_in_window)
    outside_for_verdict = _display_changes(_outside_for_verdict(outside_in_window))
    sandbox_changes = _display_sandbox(sandbox_raw, sandbox_dir)

    skipped = []
    seen_skipped = set()
    for item in list(document.get("snapshot_skipped", [])) + scan.snapshot_skipped:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        reason = item.get("reason")
        if not isinstance(path, str) or not isinstance(reason, str):
            continue
        key = (path, reason)
        if key in seen_skipped:
            continue
        seen_skipped.add(key)
        skipped.append(item)
    skipped.sort(key=lambda item: (item["path"], item["reason"]))

    no_changelog_path = (
        before.get("changelog_written_by") == []
        and not document.get("has_task_file")
    )
    result = {
        "handoff": _document_verdict(
            "HANDOFF",
            document.get("canon_handoff"),
            sandbox_changes,
            outside_for_verdict,
            sandbox_dir,
            run_document,
            snapshot_truncated=snapshot_truncated,
        ),
        "changelog": _document_verdict(
            "CHANGELOG",
            document.get("canon_changelog"),
            sandbox_changes,
            outside_for_verdict,
            sandbox_dir,
            run_document,
            no_changelog_path=no_changelog_path,
            snapshot_truncated=snapshot_truncated,
        ),
        "outside_changes": outside_changes,
        "outside_changes_out_of_window": outside_changes_out_of_window,
        "sandbox_changes": sandbox_changes,
        "run": _run_view(run_document),
        "readme_typo_fixed": _typo_fixed(document),
        "snapshot_skipped": skipped,
        "snapshot_truncated": snapshot_truncated,
    }
    if document.get("path_sanitized") or before.get("path_sanitized") or scan.path_sanitized:
        result["path_sanitized"] = True
    return write_json(sandbox_file.parent / "verdict.json", result)
