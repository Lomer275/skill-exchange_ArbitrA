from dataclasses import dataclass
import os
from pathlib import Path
import re


PROC_ROOT = Path("/proc")
_INITIAL_PROC_ROOT = PROC_ROOT
_MCP_PATTERN = re.compile(
    rb"@modelcontextprotocol/server-[a-z0-9-]+"
    rb"|mcp-server-[a-z0-9-]+"
    rb"|[a-z0-9-]+-mcp\b"
    rb"|@playwright/mcp"
    rb"|github-mcp|supabase-mcp|google-calendar-mcp",
    re.IGNORECASE,
)
_INTERPRETER_NAMES = frozenset(
    {"node", "npx", "npm", "python", "python3", "uv", "uvx", "bun", "deno"}
)


@dataclass(frozen=True)
class Proc:
    pid: int
    uid: int
    comm: str
    rss_kb: int
    mcp_names: tuple[str, ...]


def _root(proc_root: Path) -> Path:
    if proc_root == _INITIAL_PROC_ROOT and PROC_ROOT != _INITIAL_PROC_ROOT:
        return PROC_ROOT
    return proc_root


def _status(path: Path) -> tuple[int, int] | None:
    uid = None
    rss_kb = 0
    try:
        lines = path.read_text(encoding="ascii", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("Uid:"):
            fields = line.split()
            if len(fields) > 1:
                try:
                    uid = int(fields[1])
                except ValueError:
                    return None
        elif line.startswith("VmRSS:"):
            fields = line.split()
            if len(fields) > 1:
                try:
                    rss_kb = int(fields[1])
                except ValueError:
                    rss_kb = 0
    return (uid, rss_kb) if uid is not None else None


def _cmdline(pid_dir: Path) -> bytes:
    try:
        return (pid_dir / "cmdline").read_bytes()
    except OSError:
        return b""


def _is_interpreter_name(name: str) -> bool:
    return name in _INTERPRETER_NAMES or name.startswith("python3.")


def _is_interpreter(pid_dir: Path, comm: str) -> bool:
    if _is_interpreter_name(comm):
        return True
    try:
        executable = Path(os.readlink(pid_dir / "exe")).name
    except OSError:
        return False
    return _is_interpreter_name(executable)


def _mcp_names(cmdline: bytes) -> tuple[str, ...]:
    names = [
        match.group(0).decode("ascii").lower()
        for match in _MCP_PATTERN.finditer(cmdline)
    ]
    return (max(names, key=len),) if names else ()


def list_procs(uid: int | None = None, proc_root: Path = PROC_ROOT) -> list[Proc]:
    root = _root(proc_root)
    processes = []
    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError:
        return processes
    for pid_dir in entries:
        if not pid_dir.name.isdigit() or not pid_dir.is_dir():
            continue
        status = _status(pid_dir / "status")
        if status is None:
            continue
        process_uid, rss_kb = status
        if uid is not None and process_uid != uid:
            continue
        try:
            comm = (pid_dir / "comm").read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except OSError:
            comm = ""
        processes.append(
            Proc(
                pid=int(pid_dir.name),
                uid=process_uid,
                comm=comm,
                rss_kb=max(0, rss_kb),
                mcp_names=(
                    _mcp_names(_cmdline(pid_dir))
                    if _is_interpreter(pid_dir, comm)
                    else ()
                ),
            )
        )
    return processes


def executable_is(pid: int, name: str, proc_root: Path = PROC_ROOT) -> bool:
    root = _root(proc_root)
    try:
        target = os.readlink(root / str(pid) / "exe")
    except OSError:
        return False
    return target.rstrip("/").endswith("/" + name)


def editor_window_count(
    processes: list[Proc], proc_root: Path = PROC_ROOT
) -> int:
    root = _root(proc_root)
    count = 0
    for process in processes:
        if b"--type=extensionHost" in _cmdline(root / str(process.pid)):
            count += 1
    return count
