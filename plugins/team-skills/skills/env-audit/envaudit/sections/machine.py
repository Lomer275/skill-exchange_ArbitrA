import os
from pathlib import Path
import platform
import re

from envaudit.core.context import Context
from envaudit.core import runner
from envaudit.machine import backups, cgroup, disk, procs, settings


NAME = "machine"
ORDER = 10
OS_RELEASE = Path("/etc/os-release")
TOOLS = (
    "claude",
    "codex",
    "node",
    "python3",
    "git",
    "docker",
    "gh",
    "op",
    "jq",
    "rg",
    "lsof",
    "uv",
)
_VERSION = re.compile(rb"\d+(?:\.\d+)+")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _os(proc_root: Path) -> dict:
    distro = None
    release = _read_text(OS_RELEASE)
    if release is not None:
        for line in release.splitlines():
            if line.startswith("PRETTY_NAME="):
                distro = line.partition("=")[2].strip().strip("\"'")
                break
    uptime = None
    uptime_text = _read_text(proc_root / "uptime")
    if uptime_text is not None:
        try:
            uptime = int(float(uptime_text.split()[0]))
        except (ValueError, IndexError):
            pass
    return {"kernel": platform.release(), "distro": distro, "uptime_s": uptime}


def _memory(proc_root: Path) -> dict:
    values: dict[str, int] = {}
    meminfo = _read_text(proc_root / "meminfo")
    if meminfo is not None:
        for line in meminfo.splitlines():
            key, separator, rest = line.partition(":")
            if not separator:
                continue
            fields = rest.split()
            if not fields:
                continue
            try:
                values[key] = int(fields[0])
            except ValueError:
                continue
    total_kb = values.get("MemTotal")
    available_kb = values.get("MemAvailable")
    swap_total_kb = values.get("SwapTotal")
    swap_free_kb = values.get("SwapFree")
    swaps = _read_text(proc_root / "swaps")
    total_mb = total_kb // 1024 if total_kb is not None else None
    available_mb = available_kb // 1024 if available_kb is not None else None
    return {
        "total_mb": total_mb,
        "available_mb": available_mb,
        "swap_total_mb": swap_total_kb // 1024 if swap_total_kb is not None else None,
        "swap_used_mb": (
            max(0, swap_total_kb - swap_free_kb) // 1024
            if swap_total_kb is not None and swap_free_kb is not None
            else None
        ),
        "zram": "zram" in swaps.lower() if swaps is not None else None,
    }


def _tool_version(name: str, executable: str) -> str | None:
    argument = "-v" if name == "lsof" else "--version"
    result = runner.run([executable, argument], timeout=5)
    if result.rc != 0:
        return None
    match = _VERSION.search(result.stdout)
    return match.group(0).decode("ascii") if match else None


def _tools(ctx: Context) -> dict:
    host = ctx.shared.get("host")
    host = host if isinstance(host, dict) else {}
    result = {}
    for name in TOOLS:
        path = runner.which(name)
        if name in ("claude", "codex") and f"{name}_version" in host:
            version = host.get(f"{name}_version")
            version = version if isinstance(version, str) else None
        elif path is not None:
            version = _tool_version(name, path)
        else:
            version = None
        result[name] = {"path": path, "version": version}
    return result


def _projects(ctx: Context) -> dict:
    projects_dir = ctx.home / "projects"
    try:
        projects = sorted(
            (
                path
                for path in projects_dir.iterdir()
                if not path.name.startswith(".") and path.is_dir()
            ),
            key=lambda item: item.name,
        )
    except OSError:
        projects = []
    with_claude = sum((path / "CLAUDE.md").is_file() for path in projects)
    with_agents = sum((path / "AGENTS.md").is_file() for path in projects)
    return {
        "dir": "~/projects",
        "count": len(projects),
        "with_claude_md": with_claude,
        "with_agents_md": with_agents,
        "without_both": [
            path.name
            for path in projects
            if not (path / "CLAUDE.md").is_file()
            and not (path / "AGENTS.md").is_file()
        ],
    }


def _mcp(processes: list[procs.Proc], declared: dict, proc_root: Path) -> dict:
    running: dict[str, int] = {}
    for process in processes:
        for name in process.mcp_names:
            running[name] = running.get(name, 0) + 1
    return {
        "declared": declared,
        "running": dict(sorted(running.items())),
        "editor_windows": procs.editor_window_count(processes, proc_root),
    }


def _agent_stack(
    processes: list[procs.Proc], total_mb: int | None, proc_root: Path
) -> dict:
    claude = []
    codex = []
    node = []
    for process in processes:
        if process.comm == "claude" or procs.executable_is(
            process.pid, "claude", proc_root
        ):
            claude.append(process)
        if process.comm == "codex" or procs.executable_is(
            process.pid, "codex", proc_root
        ):
            codex.append(process)
        if process.comm == "node":
            node.append(process)
    unique = {process.pid: process for process in (*claude, *codex, *node)}
    rss_mb = sum(process.rss_kb for process in unique.values()) // 1024
    share = round(rss_mb / total_mb, 4) if total_mb else None
    return {
        "claude_procs": len(claude),
        "codex_procs": len(codex),
        "node_procs": len(node),
        "rss_mb": rss_mb,
        "share_of_total": share,
    }


def collect(ctx: Context) -> dict:
    host = ctx.shared.get("host")
    uid_value = host.get("uid") if isinstance(host, dict) else None
    uid = uid_value if isinstance(uid_value, int) else os.geteuid()
    proc_root = procs.PROC_ROOT
    processes = procs.list_procs(uid, proc_root)
    tools = _tools(ctx)
    declared = settings.collect_declared_mcp(ctx)
    os_facts = _os(proc_root)
    cgroup_facts = cgroup.user_slice_limits(uid, cgroup.CGROUP_ROOT)
    project_facts = _projects(ctx)
    claude_settings = settings.collect_claude_settings(ctx)
    mcp_facts = _mcp(processes, declared, proc_root)
    disk_facts = disk.collect_disk(ctx, processes, proc_root)
    backup_facts = backups.collect_backups(ctx)
    cleanup_facts = disk.cleanup_candidates(ctx, uid)
    memory = _memory(proc_root)
    return {
        "os": os_facts,
        "cgroup": cgroup_facts,
        "memory": memory,
        "tools": tools,
        "projects": project_facts,
        "claude_settings": claude_settings,
        "mcp": mcp_facts,
        "agent_stack": _agent_stack(processes, memory["total_mb"], proc_root),
        "disk": disk_facts,
        "cleanup_candidates": cleanup_facts,
        "backups": backup_facts,
    }
