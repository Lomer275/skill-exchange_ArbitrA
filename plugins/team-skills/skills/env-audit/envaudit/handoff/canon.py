from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import glob
import os
from pathlib import Path
import re

from envaudit.core import runner
from envaudit.core.dates import DateInfo, status_date
from envaudit.core.docs_layout import locate_root_file
from envaudit.core.walk import EXCLUDED_DIRS


PATH_TOKEN: str = r"[\w./{}<>*\-]*(?:HANDOFF|CHANGELOG)[\w./{}<>*\-]*\.md"

_PATH_RE = re.compile(PATH_TOKEN, re.IGNORECASE)
_DATE_MARKERS = (
    re.compile(r"\{(?:ДАТА|DATE)\}", re.IGNORECASE),
    re.compile(r"<(?:дата|date)>", re.IGNORECASE),
    re.compile(r"YYYY-MM-DD", re.IGNORECASE),
    re.compile(r"20\d\d-\d\d-\d\d"),
)


@dataclass(frozen=True)
class Declared:
    file: str
    line: int
    target: str
    is_series: bool


def normalize_target(token: str) -> str:
    result = token.replace("\\", "/")
    for pattern in _DATE_MARKERS:
        result = pattern.sub("*", result)
    return result


def declared_targets(root: Path, kind: str) -> list[Declared]:
    if kind not in {"HANDOFF", "CHANGELOG"}:
        raise ValueError(f"unknown status document kind: {kind}")
    found = []
    for name in ("CLAUDE.md", "AGENTS.md"):
        path = root / name
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, 1):
            for match in _PATH_RE.finditer(line):
                target = normalize_target(match.group(0))
                if kind not in Path(target).name.upper():
                    continue
                found.append(
                    Declared(
                        file=name,
                        line=line_no,
                        target=target,
                        is_series="*" in Path(target).name,
                    )
                )
    return found


def _target_path(root: Path, target: str) -> Path:
    path = Path(target).expanduser()
    return path if path.is_absolute() else root / path


def _display(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _head(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            return "".join(next(stream, "") for _ in range(50))
    except OSError:
        return None


def _git_date(root: Path, path: Path) -> tuple[DateInfo, bool | None]:
    rel = _display(path, root)
    result = runner.git(
        root,
        "log",
        "-1",
        "--format=%ct",
        "--no-textconv",
        "--no-ext-diff",
        "--",
        rel,
    )
    raw = result.stdout.decode("ascii", errors="ignore").strip()
    if result.rc == 0 and raw.isdigit():
        try:
            value = datetime.fromtimestamp(int(raw), timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            value = None
        info = DateInfo(value, "git", "high")
    else:
        info = status_date(path, _head(path))
    dirty_result = runner.git(
        root,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        rel,
    )
    dirty = bool(dirty_result.stdout.strip()) if dirty_result.rc == 0 else None
    return info, dirty


def _dated_view(root: Path, path: Path, *, rule: str | None = None) -> dict:
    if runner.is_git_repo(root):
        info, dirty = _git_date(root, path)
    else:
        info = status_date(path, _head(path))
        dirty = None
    result = {
        "path": _display(path, root),
        "date": info.date,
        "date_source": info.source,
        "date_trust": info.trust,
    }
    if rule is not None:
        result["rule"] = rule
        result["dirty"] = dirty
    return result


def _journal_matches(root: Path, target: str) -> list[Path]:
    pattern = str(_target_path(root, target))
    try:
        matches = [Path(item) for item in glob.glob(pattern) if Path(item).is_file()]
    except OSError:
        return []
    return sorted(matches, key=lambda path: str(path))


def _journal_view(root: Path, item: Declared) -> dict:
    matches = _journal_matches(root, item.target)
    dated = []
    for path in matches:
        info = status_date(path, _head(path))
        if info.date is not None:
            dated.append(info)
    newest = max(dated, key=lambda info: info.date or "") if dated else None
    target_path = _target_path(root, item.target)
    return {
        "glob": _display(target_path, root),
        "declared_in": f"{item.file}:{item.line}",
        "files": len(matches),
        "last": (
            {"date": newest.date, "source": newest.source, "trust": newest.trust}
            if newest is not None
            else None
        ),
    }


def _without_prefix(root: Path, kind: str) -> tuple[str | None, Path | None]:
    suffix = f"-{kind}.md"
    for rule, directory in (("root", root), ("docs", root / "docs")):
        try:
            matches = sorted(
                (
                    path
                    for path in directory.iterdir()
                    if path.is_file() and fnmatch.fnmatchcase(path.name, f"*-{kind}.md")
                ),
                key=lambda path: path.name,
            )
        except OSError:
            matches = []
        matches = [path for path in matches if path.name != suffix]
        if len(matches) == 1:
            return rule, matches[0]
    return None, None


def _candidates(root: Path, kind: str) -> list[Path]:
    result = []
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            continue
        dirs[:] = [name for name in dirs if name not in EXCLUDED_DIRS and depth < 3]
        for name in files:
            if name.lower().endswith(".md") and kind.lower() in name.lower():
                result.append(current_path / name)
    return sorted(result, key=lambda path: _display(path, root))


def find_canon(root: Path, prefix: str | None, kind: str) -> dict:
    if kind not in {"HANDOFF", "CHANGELOG"}:
        raise ValueError(f"unknown status document kind: {kind}")
    declarations = declared_targets(root, kind)
    canon_path = None
    rule = None
    for item in declarations:
        if item.is_series:
            continue
        path = _target_path(root, item.target)
        if path.is_file():
            canon_path = path
            rule = "declared"
            break

    if canon_path is None:
        if prefix is not None:
            rule, canon_path = locate_root_file(root, prefix, kind)
        else:
            rule, canon_path = _without_prefix(root, kind)

    journals_by_glob = {}
    for item in declarations:
        if not item.is_series:
            continue
        display = _display(_target_path(root, item.target), root)
        journals_by_glob.setdefault(display, item)
    journals = [
        _journal_view(root, journals_by_glob[target])
        for target in sorted(journals_by_glob)
    ]

    candidates = []
    if canon_path is None:
        candidates = [_dated_view(root, path) for path in _candidates(root, kind)]
    return {
        "canon": (
            _dated_view(root, canon_path, rule=rule)
            if canon_path is not None and rule is not None
            else None
        ),
        "journals": journals,
        "candidates": candidates,
    }
