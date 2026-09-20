from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import stat
import time

from envaudit.core.context import Context

from .procs import Proc


TMP_ROOT = Path("/tmp")
LARGE_FILE_BYTES = 200 * 1024 * 1024


def _display_path(path: Path, home: Path) -> str:
    try:
        relative = path.relative_to(home)
    except ValueError:
        return str(path)
    return "~" if not relative.parts else "~/" + relative.as_posix()


def _skip_once(ctx: Context, reason: str, details: str) -> None:
    item = {"section": "machine", "reason": reason, "details": details}
    if item not in ctx.skipped:
        ctx.skip("machine", reason, details=details)


def _out_of_time(ctx: Context, deadline: float) -> bool:
    return time.time() >= deadline or ctx.expired()


def _measure(
    path: Path,
    ctx: Context,
    deadline: float,
    *,
    device: int | None = None,
    collect_large: bool = False,
) -> tuple[int, bool, list[tuple[Path, int, float]]]:
    if _out_of_time(ctx, deadline):
        return 0, True, []
    try:
        root_stat = path.lstat()
    except OSError:
        _skip_once(ctx, "permission", _display_path(path, ctx.home))
        return 0, True, []
    if device is None:
        device = root_stat.st_dev
    if root_stat.st_dev != device:
        return 0, False, []

    total = max(0, getattr(root_stat, "st_blocks", 0)) * 512
    large = []
    if stat.S_ISLNK(root_stat.st_mode):
        return total, False, large
    if not stat.S_ISDIR(root_stat.st_mode):
        if (
            collect_large
            and stat.S_ISREG(root_stat.st_mode)
            and root_stat.st_size > LARGE_FILE_BYTES
        ):
            large.append((path, root_stat.st_size, root_stat.st_mtime))
        return total, False, large

    stack = [path]
    partial = False
    while stack:
        if _out_of_time(ctx, deadline):
            partial = True
            break
        directory = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except OSError:
            _skip_once(ctx, "permission", _display_path(directory, ctx.home))
            partial = True
            continue
        for entry in entries:
            if _out_of_time(ctx, deadline):
                partial = True
                stack.clear()
                break
            try:
                item_stat = entry.stat(follow_symlinks=False)
            except OSError:
                _skip_once(ctx, "permission", _display_path(Path(entry.path), ctx.home))
                partial = True
                continue
            if item_stat.st_dev != device:
                continue
            total += max(0, getattr(item_stat, "st_blocks", 0)) * 512
            if stat.S_ISLNK(item_stat.st_mode):
                continue
            if stat.S_ISDIR(item_stat.st_mode):
                stack.append(Path(entry.path))
            elif (
                collect_large
                and stat.S_ISREG(item_stat.st_mode)
                and item_stat.st_size > LARGE_FILE_BYTES
            ):
                large.append((Path(entry.path), item_stat.st_size, item_stat.st_mtime))
    return total, partial, large


def dir_size(path: Path, ctx: Context, *, deadline: float) -> tuple[int, bool]:
    size, partial, _ = _measure(path, ctx, deadline)
    return size, partial


def _scan_home(
    ctx: Context, deadline: float
) -> tuple[list[dict], int, bool, list[dict]]:
    try:
        home_stat = ctx.home.stat()
        entries = sorted(ctx.home.iterdir(), key=lambda item: item.name)
    except OSError:
        _skip_once(ctx, "permission", "~")
        return [], 0, True, []

    sizes = []
    large_files: list[tuple[Path, int, float]] = []
    partial = False
    for entry in entries:
        if _out_of_time(ctx, deadline):
            partial = True
            break
        size, item_partial, item_large = _measure(
            entry,
            ctx,
            deadline,
            device=home_stat.st_dev,
            collect_large=True,
        )
        sizes.append({"name": entry.name, "bytes": size})
        large_files.extend(item_large)
        partial = partial or item_partial
        if item_partial and _out_of_time(ctx, deadline):
            break

    if partial and _out_of_time(ctx, deadline):
        _skip_once(ctx, "budget", "disk.home")
        ctx.mark_truncated()
    sizes.sort(key=lambda item: (-item["bytes"], item["name"]))
    large_files.sort(key=lambda item: (-item[1], str(item[0])))
    large_view = [
        {
            "path": _display_path(path, ctx.home),
            "bytes": size,
            "date": datetime.fromtimestamp(mtime, timezone.utc).date().isoformat(),
        }
        for path, size, mtime in large_files[:12]
    ]
    return sizes[:15], sum(item["bytes"] for item in sizes), partial, large_view


def _gib(value: int) -> float:
    return round(value / (1024 ** 3), 1)


def _filesystems(ctx: Context) -> list[dict]:
    result = []
    seen_devices = set()
    for path in (Path("/"), ctx.home, *ctx.roots):
        try:
            device = path.stat().st_dev
            usage = shutil.disk_usage(path)
        except OSError:
            _skip_once(ctx, "permission", _display_path(path, ctx.home))
            continue
        if device in seen_devices:
            continue
        seen_devices.add(device)
        available = usage.used + usage.free
        result.append(
            {
                "mount": str(path),
                "total_gb": _gib(usage.total),
                "used_gb": _gib(usage.used),
                "free_gb": _gib(usage.free),
                "reserved_gb": _gib(usage.total - usage.used - usage.free),
                "used_pct": (
                    round(usage.used * 100 / available, 1) if available else 0.0
                ),
            }
        )
    return result


def _deleted_open(processes: list[Proc], proc_root: Path) -> dict:
    seen = set()
    total = 0
    for process in processes:
        fd_dir = proc_root / str(process.pid) / "fd"
        try:
            descriptors = list(fd_dir.iterdir())
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor)
            except OSError:
                continue
            if not target.endswith(" (deleted)"):
                continue
            try:
                item_stat = descriptor.stat()
            except OSError:
                continue
            identity = (item_stat.st_dev, item_stat.st_ino)
            if identity in seen:
                continue
            seen.add(identity)
            total += max(0, item_stat.st_size)
    return {"files": len(seen), "bytes": total}


def collect_disk(ctx: Context, processes: list[Proc], proc_root: Path) -> dict:
    deadline = min(ctx.deadline, time.time() + 90)
    home_top, visible_bytes, partial, large_files = _scan_home(ctx, deadline)
    try:
        home_used = shutil.disk_usage(ctx.home).used
    except OSError:
        home_used = None
        _skip_once(ctx, "permission", "disk.home_usage")
    return {
        "filesystems": _filesystems(ctx),
        "home_top": home_top,
        "home_visible_gb": _gib(visible_bytes),
        "home_fs_used_gb": _gib(home_used) if home_used is not None else None,
        "home_partial": partial,
        "large_files": large_files,
        "deleted_open": _deleted_open(processes, proc_root),
    }


def _jsonl_size(path: Path, ctx: Context, deadline: float) -> tuple[int, bool]:
    total = 0
    partial = False
    try:
        root_device = path.stat().st_dev
    except OSError:
        return 0, False
    stack = [path]
    while stack:
        if _out_of_time(ctx, deadline):
            return total, True
        directory = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except OSError:
            partial = True
            continue
        for entry in entries:
            try:
                item_stat = entry.stat(follow_symlinks=False)
            except OSError:
                partial = True
                continue
            if item_stat.st_dev != root_device or stat.S_ISLNK(item_stat.st_mode):
                continue
            if stat.S_ISDIR(item_stat.st_mode):
                stack.append(Path(entry.path))
            elif stat.S_ISREG(item_stat.st_mode) and entry.name.endswith(".jsonl"):
                total += max(0, getattr(item_stat, "st_blocks", 0)) * 512
    return total, partial


def cleanup_candidates(ctx: Context, uid: int) -> list[dict]:
    host = ctx.shared.get("host")
    codex_home_value = host.get("codex_home") if isinstance(host, dict) else None
    codex_home = (
        Path(codex_home_value)
        if isinstance(codex_home_value, str)
        else ctx.home / ".codex"
    )
    candidates: list[tuple[Path, str, bool]] = [
        (ctx.home / ".cache", "cache", False),
        (ctx.home / ".npm" / "_cacache", "cache", False),
        (ctx.home / ".cache" / "pip", "cache", False),
        (ctx.home / ".claude" / "projects", "transcripts", True),
        (codex_home / "sessions", "transcripts", False),
    ]
    try:
        temporary = sorted(TMP_ROOT.glob("claude-*"), key=lambda item: item.name)
    except OSError:
        temporary = []
    for path in temporary:
        try:
            if path.lstat().st_uid == uid:
                candidates.append((path, "tmp", False))
        except OSError:
            continue

    deadline = ctx.deadline
    result = []
    for path, kind, jsonl_only in candidates:
        if not path.exists() or path.is_symlink():
            continue
        if _out_of_time(ctx, deadline):
            _skip_once(ctx, "budget", "cleanup_candidates")
            ctx.mark_truncated()
            break
        if jsonl_only:
            size, _ = _jsonl_size(path, ctx, deadline)
        else:
            size, _ = dir_size(path, ctx, deadline=deadline)
        result.append(
            {"path": _display_path(path, ctx.home), "bytes": size, "kind": kind}
        )
    return result
