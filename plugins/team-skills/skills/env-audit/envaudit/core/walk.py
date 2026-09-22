from collections.abc import Iterator
from dataclasses import dataclass
import os
from pathlib import Path

from . import osinfo
from .context import Context


EXCLUDED_DIRS = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache"}
)


@dataclass(frozen=True)
class FileEntry:
    path: Path
    rel: str
    size: int
    mtime: float
    is_symlink: bool
    symlink_inside_root: bool | None


def audit_backup_dirs(home: Path) -> tuple[Path, ...]:
    try:
        return tuple(
            sorted(
                (path for path in home.glob("audit-*") if path.is_dir()),
                key=lambda path: path.name,
            )
        )
    except OSError:
        return ()


def windows_home_exclusions(home: Path) -> tuple[Path, ...]:
    if not osinfo.is_windows():
        return ()
    local = home / "AppData" / "Local"
    return tuple(
        local / name
        for name in (
            "Temp",
            "Packages",
            "Microsoft",
            "Google",
            "Mozilla",
            "BraveSoftware",
            "Yandex",
        )
    )


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _inside(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(parent))) == str(parent)
    except ValueError:
        return False


def iter_files(
    root: Path,
    ctx: Context,
    section: str,
    *,
    exclude_dirs: frozenset[str] = EXCLUDED_DIRS,
    exclude_paths: tuple[Path, ...] = (),
    max_depth: int | None = None,
) -> Iterator[FileEntry]:
    root = _absolute(root)
    blocked = {
        _absolute(path) for path in (*exclude_paths, *audit_backup_dirs(ctx.home))
    }
    if any(_inside(root, path) for path in blocked):
        return

    def onerror(error: OSError) -> None:
        failed = Path(error.filename) if error.filename else root
        try:
            details = failed.relative_to(root).as_posix() or "."
        except ValueError:
            details = failed.name or "."
        ctx.skip(section, "permission", details=details)

    for current, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            continue

        kept_dirs = []
        for dirname in dirs:
            candidate = _absolute(current_path / dirname)
            if dirname in exclude_dirs or candidate in blocked:
                continue
            kept_dirs.append(dirname)
        dirs[:] = kept_dirs if max_depth is None or depth < max_depth else []

        for filename in files:
            path = current_path / filename
            if _absolute(path) in blocked:
                continue
            try:
                stat = path.lstat()
            except OSError:
                onerror(OSError(0, "stat failed", str(path)))
                continue
            is_symlink = path.is_symlink()
            inside: bool | None = None
            if is_symlink:
                try:
                    target = Path(os.path.realpath(path))
                    inside = _inside(target, root)
                except OSError:
                    inside = False
            yield FileEntry(
                path=path,
                rel=path.relative_to(root).as_posix(),
                size=stat.st_size,
                mtime=stat.st_mtime,
                is_symlink=is_symlink,
                symlink_inside_root=inside,
            )


def read_limited(entry: FileEntry, max_bytes: int) -> bytes | None:
    if entry.size > max_bytes or entry.is_symlink:
        return None
    try:
        return entry.path.read_bytes()
    except OSError:
        return None
