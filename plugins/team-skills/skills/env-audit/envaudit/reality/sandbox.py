from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from envaudit.core.dates import status_date
from envaudit.core.patterns import find
from envaudit.reality import snapshot


TYPO_LINE = "Проверка аудита: в этой строке есть опечаткаа."
ROOT_FILES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "README.md")
TASK_NAME = "T999_env_audit_reality_check.md"


class PrepareError(Exception):
    def __init__(self, code: int, payload: dict):
        super().__init__(str(payload))
        self.code = code
        self.payload = payload


def write_json(path: Path, document: dict) -> dict:
    path_sanitized = False

    def safe(value):
        nonlocal path_sanitized
        if isinstance(value, str):
            stored = value.encode("utf-8", "replace").decode("utf-8")
            path_sanitized = path_sanitized or stored != value
            return stored
        if isinstance(value, list):
            return [safe(item) for item in value]
        if isinstance(value, dict):
            return {safe(key): safe(item) for key, item in value.items()}
        return value

    stored = safe(document)
    if path_sanitized:
        stored["path_sanitized"] = True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(stored, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return stored


def read_json(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("expected JSON object")
    return document


def memory_dir_name(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(path))


def memory_path(sandbox: Path) -> Path:
    return Path.home() / ".claude" / "projects" / memory_dir_name(sandbox) / "memory"


def _inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((os.path.realpath(path), os.path.realpath(root))) == os.path.realpath(root)
    except (OSError, ValueError):
        return False


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _symlinks(root: Path) -> list[str]:
    result = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        if current_path == root:
            dirnames[:] = [name for name in dirnames if name != ".git"]
        for name in list(dirnames):
            path = current_path / name
            if path.is_symlink():
                result.append(_relative(path, root))
                dirnames.remove(name)
        for name in filenames:
            path = current_path / name
            if path.is_symlink():
                result.append(_relative(path, root))
    return sorted(set(result))


def _copy_file(
    source: Path,
    root: Path,
    sandbox: Path,
    excluded: list[dict],
    skipped: list[str],
) -> bool:
    if not _inside(source, root) or not source.is_file():
        return False
    rel = _relative(source, root)
    if source.is_symlink():
        skipped.append(rel)
        return False
    try:
        data = source.read_bytes()
    except OSError:
        return False
    matches = find(data)
    if matches:
        for cls in sorted({item.cls for item in matches}):
            excluded.append({"class": cls, "path": rel})
        return False
    destination = sandbox / rel
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination, follow_symlinks=False)
    return True


def _copy_claude(root: Path, sandbox: Path, excluded: list[dict], skipped: list[str]) -> None:
    source_root = root / ".claude"
    if not source_root.is_dir() or source_root.is_symlink():
        return
    for current, dirnames, filenames in os.walk(source_root, followlinks=False):
        current_path = Path(current)
        for name in list(dirnames):
            path = current_path / name
            if path.is_symlink():
                skipped.append(_relative(path, root))
                dirnames.remove(name)
        for name in filenames:
            _copy_file(current_path / name, root, sandbox, excluded, skipped)


def _journal_files(root: Path, pattern: str) -> list[Path]:
    candidate = Path(pattern).expanduser()
    raw = str(candidate if candidate.is_absolute() else root / candidate)
    paths = [Path(value) for value in glob.glob(raw)]
    paths = [path for path in paths if path.is_file() and _inside(path, root)]

    def key(path: Path) -> tuple[str, float, str]:
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:8192]
            mtime = path.stat().st_mtime
        except OSError:
            head, mtime = "", 0.0
        value = status_date(path, head)
        return value.date or "", mtime, str(path)

    return sorted(paths, key=key, reverse=True)[:5]


def _task_file(root: Path, sandbox: Path) -> Path | None:
    docs = root / "docs"
    try:
        candidates = sorted(
            path
            for path in docs.iterdir()
            if path.is_dir() and re.fullmatch(r"3\. .+-tasks", path.name)
        )
    except OSError:
        candidates = []
    if not candidates:
        return None
    destination = sandbox / "docs" / candidates[0].name / TASK_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "---\n"
        "spec: env-audit\n"
        "status: in_progress\n"
        "---\n\n"
        "# T999. Проверка аудита рабочего места\n\n"
        "## Критерии приёмки\n\n"
        "- опечатка в README исправлена\n",
        encoding="utf-8",
    )
    return destination


def _root_data(facts: dict, root: Path) -> dict:
    sections = facts.get("sections")
    handoff = sections.get("handoff") if isinstance(sections, dict) else None
    roots = handoff.get("roots") if isinstance(handoff, dict) else None
    if not isinstance(roots, dict):
        raise PrepareError(2, {"error": "handoff_root_not_found"})
    for raw, value in roots.items():
        if isinstance(raw, str) and os.path.realpath(raw) == str(root) and isinstance(value, dict):
            return value
    raise PrepareError(2, {"error": "handoff_root_not_found"})


def _canon_path(document: dict | None, root: Path) -> Path | None:
    canon = document.get("canon") if isinstance(document, dict) else None
    raw = canon.get("path") if isinstance(canon, dict) else None
    if not isinstance(raw, str):
        return None
    path = Path(raw).expanduser()
    return path if path.is_absolute() else root / path


def prepare(facts: dict, root: Path, out_dir: Path) -> dict:
    profile = facts.get("host", {}).get("profile") if isinstance(facts.get("host"), dict) else None
    if profile not in ("claude", "both"):
        raise PrepareError(5, {"not_applicable": f"profile={profile}"})
    root = Path(os.path.realpath(root))
    if not root.is_dir():
        raise PrepareError(2, {"error": "root_not_found"})
    root_data = _root_data(facts, root)
    out_dir = Path(os.path.abspath(out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    sandbox = Path(tempfile.mkdtemp(prefix="env-audit-sbx-"))
    sandbox.chmod(0o700)
    excluded: list[dict] = []
    skipped = _symlinks(root)
    try:
        for name in ROOT_FILES:
            _copy_file(root / name, root, sandbox, excluded, skipped)
        _copy_claude(root, sandbox, excluded, skipped)

        handoff_source = _canon_path({"canon": root_data.get("canon")}, root)
        changelog_document = root_data.get("changelog")
        changelog_source = _canon_path(changelog_document, root)
        for source in (handoff_source, changelog_source):
            if source is not None:
                _copy_file(source, root, sandbox, excluded, skipped)

        journal_globs = []
        documents = [root_data, changelog_document]
        for document in documents:
            journals = document.get("journals") if isinstance(document, dict) else None
            if not isinstance(journals, list):
                continue
            for journal in journals:
                pattern = journal.get("glob") if isinstance(journal, dict) else None
                if not isinstance(pattern, str):
                    continue
                journal_globs.append(pattern)
                for source in _journal_files(root, pattern):
                    _copy_file(source, root, sandbox, excluded, skipped)

        task = _task_file(root, sandbox)
        readme = sandbox / "README.md"
        with readme.open("a", encoding="utf-8") as stream:
            if readme.stat().st_size:
                stream.write("\n")
            stream.write(TYPO_LINE + "\n")

        owned_paths = [sandbox, memory_path(sandbox)]
        scan = snapshot.ScanState()
        before = {
            "outside": snapshot.take(
                snapshot.expand_targets(),
                exclude=owned_paths,
                state=scan,
            ),
            "sandbox": snapshot.take([sandbox], exclude=[], state=scan),
            "changelog_written_by": (
                root_data.get("changelog_written_by")
                if isinstance(root_data.get("changelog_written_by"), list)
                else []
            ),
            "snapshot_skipped": sorted(
                scan.snapshot_skipped,
                key=lambda item: (item["path"], item["reason"]),
            ),
            "snapshot_truncated": scan.truncated,
        }
        if scan.path_sanitized:
            before["path_sanitized"] = True
        write_json(out_dir / "snapshot_before.json", before)

        path_sanitized = scan.path_sanitized

        def stored_path(value: str | os.PathLike[str]) -> str:
            nonlocal path_sanitized
            stored, sanitized = snapshot.safe_path(value)
            path_sanitized = path_sanitized or sanitized
            return stored

        def inside_copy(source: Path | None) -> str | None:
            if source is None or not _inside(source, root):
                return None
            return stored_path(sandbox / _relative(source, root))

        stored_excluded = []
        for item in sorted(excluded, key=lambda value: (value["path"], value["class"])):
            stored, sanitized = snapshot.safe_path(item["path"])
            path_sanitized = path_sanitized or sanitized
            value = {"class": item["class"], "path": stored}
            if sanitized:
                value["path_sanitized"] = True
            stored_excluded.append(value)

        stored_skipped = sorted({stored_path(item) for item in set(skipped)})

        document = {
            "sandbox": stored_path(sandbox),
            "root": stored_path(root),
            "canon_handoff": inside_copy(handoff_source),
            "canon_changelog": inside_copy(changelog_source),
            "journal_globs": sorted({stored_path(item) for item in set(journal_globs)}),
            "has_task_file": task is not None,
            "typo_line": TYPO_LINE,
            "owned_paths": [stored_path(item) for item in owned_paths],
            "excluded_secret": stored_excluded,
            "skipped_symlinks": stored_skipped,
            "snapshot_skipped": before["snapshot_skipped"],
            "snapshot_truncated": scan.truncated,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if path_sanitized:
            document["path_sanitized"] = True
        return write_json(out_dir / "sandbox.json", document)
    except Exception:
        shutil.rmtree(sandbox, ignore_errors=True)
        raise
