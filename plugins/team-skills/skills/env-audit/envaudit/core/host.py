import os
from pathlib import Path
import platform
import pwd
import re
import socket

from .context import Context
from .runner import run, which


def _version(command: str) -> str | None:
    executable = which(command)
    if executable is None:
        return None
    result = run([executable, "--version"], timeout=15)
    if result.rc != 0:
        return None
    match = re.search(rb"\d+\.\d+\.\d+", result.stdout)
    return match.group(0).decode("ascii") if match else None


def _logged_in_count() -> int | None:
    executable = which("who")
    if executable is None:
        return None
    result = run([executable], timeout=15)
    if result.rc != 0:
        return None
    users = {
        line.split(None, 1)[0]
        for line in result.stdout.splitlines()
        if line.split(None, 1)
    }
    return len(users)


def _mem_total_mb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def collect_host(ctx: Context) -> dict:
    account = pwd.getpwuid(os.geteuid())
    codex_home = Path(os.environ.get("CODEX_HOME", str(ctx.home / ".codex")))
    codex_home = Path(os.path.realpath(codex_home.expanduser()))
    has_claude = which("claude") is not None or (ctx.home / ".claude").is_dir()
    has_codex = which("codex") is not None or codex_home.is_dir()
    if has_claude and has_codex:
        profile = "both"
    elif has_claude:
        profile = "claude"
    elif has_codex:
        profile = "codex"
    else:
        profile = "none"

    users_with_home = sum(
        1
        for entry in pwd.getpwall()
        if 1000 <= entry.pw_uid < 65534 and Path(entry.pw_dir).is_dir()
    )
    return {
        "user": account.pw_name,
        "uid": os.geteuid(),
        "home": str(ctx.home),
        "hostname": socket.gethostname(),
        "python": platform.python_version(),
        "profile": profile,
        "codex_home": str(codex_home),
        "claude_version": _version("claude"),
        "codex_version": _version("codex"),
        "users_with_home": users_with_home,
        "logged_in_count": _logged_in_count(),
        "cpu_count": os.cpu_count(),
        "mem_total_mb": _mem_total_mb(),
        "linked_worktrees_skipped": int(
            ctx.shared.get("linked_worktrees_skipped", 0)
        ),
    }
