from itertools import islice
import os
from pathlib import Path

from envaudit.core.context import Context
from envaudit.core.dates import DateInfo, status_date


NAME = "memory_codex"
ORDER = 66


def _display(path: Path, home: Path) -> str:
    try:
        return "~/" + path.relative_to(home).as_posix()
    except ValueError:
        return str(path)


def _head(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            return "".join(islice(stream, 50))
    except OSError:
        return None


def _view(info: DateInfo | None) -> dict | None:
    if info is None:
        return None
    return {"date": info.date, "source": info.source, "trust": info.trust}


def collect(ctx: Context) -> dict:
    host = ctx.shared.get("host", {})
    raw_home = host.get("codex_home") if isinstance(host, dict) else None
    codex_home = Path(raw_home) if isinstance(raw_home, str) else Path(
        os.environ.get("CODEX_HOME", str(ctx.home / ".codex"))
    )
    memory_dir = Path(os.path.realpath(codex_home.expanduser())) / "memories"
    if not memory_dir.is_dir():
        return {
            "dir": _display(memory_dir, ctx.home),
            "exists": False,
            "files": 0,
            "bytes": 0,
            "newest": None,
            "oldest": None,
        }

    files = []
    total_bytes = 0
    try:
        candidates = sorted(memory_dir.rglob("*"))
    except OSError:
        candidates = []
    for path in candidates:
        try:
            if not path.is_file() or path.is_symlink():
                continue
            total_bytes += path.stat().st_size
        except OSError:
            continue
        info = status_date(path, _head(path))
        if info.date is not None:
            files.append(info)
    explicit_dates = [item for item in files if item.source != "mtime"]
    dated = explicit_dates or files
    newest = max(dated, key=lambda item: item.date or "") if dated else None
    oldest = min(dated, key=lambda item: item.date or "") if dated else None
    return {
        "dir": _display(memory_dir, ctx.home),
        "exists": True,
        "files": len(files),
        "bytes": total_bytes,
        "newest": _view(newest),
        "oldest": _view(oldest),
    }
