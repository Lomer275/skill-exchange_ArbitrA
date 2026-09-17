from pathlib import Path
import re
import time

from envaudit.core.context import Context
from envaudit.core.runner import run


VAR_BACKUPS = Path("/var/backups")
_BACKUP_LINE = re.compile(rb"backup|rsync|restic|borg|pg_dump|tar ", re.IGNORECASE)


def _timer_names(stdout: bytes) -> list[str]:
    names = set()
    for line in stdout.splitlines():
        for field in line.split():
            if field.endswith(b".timer"):
                names.add(field.decode("utf-8", errors="replace"))
                break
    return sorted(names)


def _cron_counts(stdout: bytes) -> tuple[int, int]:
    entries = 0
    backup_like = 0
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(b"#"):
            continue
        entries += 1
        if _BACKUP_LINE.search(line):
            backup_like += 1
    return entries, backup_like


def _recent_days(path: Path) -> int | None:
    try:
        entries = list(path.iterdir())
    except OSError:
        return None
    mtimes = []
    for item in entries:
        try:
            mtimes.append(item.stat().st_mtime)
        except OSError:
            continue
    if not mtimes:
        return None
    return max(0, int((time.time() - max(mtimes)) // 86400))


def collect_backups(ctx: Context) -> dict:
    del ctx
    timers_result = run(
        ["systemctl", "--user", "list-timers", "--all", "--no-legend"],
        timeout=5,
    )
    timers = _timer_names(timers_result.stdout) if timers_result.rc == 0 else None

    cron_result = run(["crontab", "-l"], timeout=5)
    if cron_result.rc in (0, 1):
        cron_entries, cron_backup_like = _cron_counts(cron_result.stdout)
    else:
        cron_entries = None
        cron_backup_like = None

    return {
        "user_timers": timers,
        "cron_entries": cron_entries,
        "cron_backup_like": cron_backup_like,
        "var_backups_recent_days": _recent_days(VAR_BACKUPS),
    }
