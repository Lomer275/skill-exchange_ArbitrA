from dataclasses import dataclass, field
import glob
import hashlib
import os
from pathlib import Path
import stat as stat_module
import time


MAX_HASH_BYTES = 20 * 1024 * 1024
MAX_FILES = 200_000
MAX_SECONDS = 60.0
OUTSIDE_TARGETS = (
    "~/.claude/projects/*/memory",
    "~/.claude/CLAUDE.md",
    "~/.claude/settings.json",
    "~/.claude/skills",
    "$CODEX_HOME/AGENTS.md",
    "$CODEX_HOME/memories",
    "/tmp/claude-*",
    "/tmp/sup-codex",
)


def safe_path(path: str | os.PathLike[str]) -> tuple[str, bool]:
    raw = os.fspath(path)
    value = str(raw).encode("utf-8", "replace").decode("utf-8")
    return value, value != raw


def _absolute(path: Path) -> str:
    return os.path.abspath(os.fspath(path))


def _inside(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((_absolute(path), _absolute(parent))) == _absolute(parent)
    except ValueError:
        return False


def _reason(error: OSError) -> str:
    if isinstance(error, PermissionError):
        return "permission_denied"
    if error.errno is not None:
        return f"os_error_{error.errno}"
    return "os_error"


@dataclass
class ScanState:
    started_at: float = field(default_factory=lambda: time.monotonic())
    files: int = 0
    truncated: bool = False
    path_sanitized: bool = False
    snapshot_skipped: list[dict] = field(default_factory=list)
    _skipped_keys: set[tuple[str, str]] = field(default_factory=set, repr=False)

    def check_time(self) -> bool:
        if self.truncated:
            return False
        if time.monotonic() - self.started_at >= MAX_SECONDS:
            self.truncated = True
            return False
        return True

    def start_file(self) -> bool:
        if not self.check_time():
            return False
        if self.files >= MAX_FILES:
            self.truncated = True
            return False
        self.files += 1
        return True

    def skip(self, path: Path, error: OSError) -> None:
        value, sanitized = safe_path(_absolute(path))
        reason = _reason(error)
        key = (value, reason)
        if key in self._skipped_keys:
            return
        self._skipped_keys.add(key)
        item = {"path": value, "reason": reason}
        if sanitized:
            item["path_sanitized"] = True
            self.path_sanitized = True
        self.snapshot_skipped.append(item)


def expand_targets(patterns: tuple[str, ...] | None = None) -> list[Path]:
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME", str(home / ".codex"))).expanduser()
    result = []
    seen = set()
    for raw in patterns or OUTSIDE_TARGETS:
        expanded = raw.replace("$CODEX_HOME", str(codex_home))
        expanded = os.path.expanduser(expanded)
        matches = glob.glob(expanded)
        candidates = matches or ([] if glob.has_magic(expanded) else [expanded])
        for candidate in candidates:
            path = Path(os.path.abspath(candidate))
            if str(path) in seen:
                continue
            seen.add(str(path))
            result.append(path)
    return result


def _metadata(path: Path, state: ScanState, path_stat: os.stat_result) -> dict | None:
    digest = None
    if stat_module.S_ISREG(path_stat.st_mode) and path_stat.st_size <= MAX_HASH_BYTES:
        try:
            handle = hashlib.sha1()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    if not state.check_time():
                        return None
                    handle.update(chunk)
            digest = handle.hexdigest()
        except OSError as error:
            state.skip(path, error)
            return None
    return {"size": path_stat.st_size, "sha1": digest, "mtime": path_stat.st_mtime}


def _claude_tmp_dir(path: Path, path_stat: os.stat_result) -> bool:
    return (
        stat_module.S_ISDIR(path_stat.st_mode)
        and os.path.dirname(_absolute(path)) == "/tmp"
        and os.path.basename(_absolute(path)).startswith("claude-")
    )


def take(
    paths: list[Path],
    *,
    exclude: list[Path],
    state: ScanState | None = None,
) -> dict[str, dict]:
    scan = state or ScanState()
    excluded = [Path(_absolute(path)) for path in exclude]
    result: dict[str, dict] = {}

    def excluded_path(path: Path) -> bool:
        return any(_inside(path, item) for item in excluded)

    def record(path: Path, path_stat: os.stat_result | None = None) -> bool:
        if excluded_path(path):
            return True
        if path_stat is None:
            try:
                path_stat = path.stat(follow_symlinks=False)
            except OSError as error:
                scan.skip(path, error)
                return True
        if stat_module.S_ISLNK(path_stat.st_mode):
            return True
        if not scan.start_file():
            return False
        value = _metadata(path, scan, path_stat)
        if value is None:
            return not scan.truncated
        key, sanitized = safe_path(_absolute(path))
        if sanitized:
            value["path_sanitized"] = True
            scan.path_sanitized = True
        result[key] = value
        return not scan.truncated

    for raw_target in paths:
        if not scan.check_time():
            break
        target = Path(_absolute(raw_target))
        if excluded_path(target):
            continue
        try:
            target_stat = target.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError as error:
            scan.skip(target, error)
            continue
        if _claude_tmp_dir(target, target_stat) and target_stat.st_uid != os.getuid():
            continue
        if stat_module.S_ISLNK(target_stat.st_mode):
            continue
        if not stat_module.S_ISDIR(target_stat.st_mode):
            if not record(target, target_stat):
                break
            continue

        def walk_error(error: OSError) -> None:
            filename = error.filename
            scan.skip(Path(filename) if filename is not None else target, error)

        stop = False
        for current, dirnames, filenames in os.walk(
            target,
            followlinks=False,
            onerror=walk_error,
        ):
            if not scan.check_time():
                stop = True
                break
            current_path = Path(current)
            kept = []
            for name in dirnames:
                path = current_path / name
                if excluded_path(path):
                    continue
                try:
                    child_stat = path.stat(follow_symlinks=False)
                except OSError as error:
                    scan.skip(path, error)
                    continue
                if not stat_module.S_ISLNK(child_stat.st_mode):
                    kept.append(name)
            dirnames[:] = kept
            for name in filenames:
                if not record(current_path / name):
                    stop = True
                    break
            if stop:
                break
        if stop:
            break
    return dict(sorted(result.items()))


def diff(before: dict, after: dict, *, run_started: float | None) -> dict:
    before_paths = set(before)
    after_paths = set(after)
    created = [
        path
        for path in after_paths - before_paths
        if run_started is None
        or float(after[path].get("mtime", 0.0)) >= run_started
    ]
    modified = [
        path
        for path in before_paths & after_paths
        if before[path] != after[path]
        and (
            run_started is None
            or float(after[path].get("mtime", 0.0)) >= run_started
        )
    ]
    return {
        "created": sorted(created),
        "modified": sorted(modified),
        "deleted": sorted(before_paths - after_paths),
    }
