import json
import os
from pathlib import Path
import time

from envaudit.core.context import Context, Flags
from envaudit.machine import backups, cgroup, disk, procs, settings
from envaudit.sections import machine

from .canaries import canary, fragments
from .schema_check import validate


def _context(
    home: Path,
    roots: list[Path] | None = None,
    *,
    deadline: float | None = None,
) -> Context:
    started = time.time()
    return Context(
        flags=Flags(),
        home=home,
        roots=roots or [],
        started_at=started,
        deadline=deadline if deadline is not None else started + 300,
        shared={
            "host": {
                "uid": os.geteuid(),
                "codex_home": str(home / ".codex"),
                "claude_version": None,
                "codex_version": None,
            }
        },
    )


def _fake_proc(
    proc_root: Path,
    pid: int,
    *,
    comm: str,
    rss_kb: int,
    cmdline: bytes = b"",
) -> None:
    directory = proc_root / str(pid)
    directory.mkdir(parents=True)
    (directory / "status").write_text(
        f"Name:\t{comm}\nUid:\t{os.geteuid()}\t{os.geteuid()}\t{os.geteuid()}\t{os.geteuid()}\nVmRSS:\t{rss_kb} kB\n",
        encoding="ascii",
    )
    (directory / "comm").write_text(comm + "\n", encoding="utf-8")
    (directory / "cmdline").write_bytes(cmdline)


def test_cgroup_parse(tmp_path, monkeypatch):
    root = tmp_path / "cgroup"
    user_slice = root / "user.slice" / f"user-{os.geteuid()}.slice"
    user_slice.mkdir(parents=True)
    (user_slice / "memory.high").write_text("6442450944\n", encoding="ascii")
    (user_slice / "memory.max").write_text("max\n", encoding="ascii")
    (user_slice / "memory.events.local").write_text("high 12\n", encoding="ascii")
    monkeypatch.setattr(cgroup, "SYSTEMD_SYSTEM_ROOT", tmp_path / "systemd")

    result = cgroup.user_slice_limits(os.geteuid(), root)

    assert result["memory_high_mb"] == 6144
    assert result["memory_max_mb"] is None
    assert result["events_high"] == 12


def test_procs_no_cmdline_leak(tmp_path):
    sample = canary("generic_assignment", seed=452)
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _fake_proc(
        proc_root,
        101,
        comm="node",
        rss_kb=2048,
        cmdline=b"node\0/x/mcp-server-playwright\0--token\0" + sample.encode(),
    )
    _fake_proc(proc_root, 102, comm="claude", rss_kb=1024, cmdline=b"claude\0")

    processes = procs.list_procs(os.geteuid(), proc_root)
    result = machine._mcp(processes, {"user": [], "projects": {}}, proc_root)
    rendered = json.dumps(result)

    assert result["running"] == {"mcp-server-playwright": 1}
    assert all(fragment not in rendered for fragment in fragments(sample))


def test_mcp_one_name_per_process(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _fake_proc(
        proc_root,
        101,
        comm="node",
        rss_kb=2048,
        cmdline=b"node\0/x/node_modules/@playwright/mcp/cli.js\0--headless\0",
    )
    _fake_proc(
        proc_root,
        102,
        comm="node",
        rss_kb=2048,
        cmdline=b"npx\0mcp-server-filesystem\0/tmp\0",
    )

    processes = procs.list_procs(os.geteuid(), proc_root)
    result = machine._mcp(processes, {"user": [], "projects": {}}, proc_root)

    assert all(len(process.mcp_names) <= 1 for process in processes)
    assert sum(result["running"].values()) == 2


def test_mcp_ignores_browser_processes(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _fake_proc(
        proc_root,
        101,
        comm="chrome",
        rss_kb=2048,
        cmdline=(
            b"/home/u/.cache/ms-playwright/chromium-1140/chrome-linux/chrome\0"
            b"--type=renderer\0"
        ),
    )
    _fake_proc(
        proc_root,
        102,
        comm="node",
        rss_kb=2048,
        cmdline=b"node\0/x/node_modules/@playwright/mcp/cli.js\0",
    )

    processes = procs.list_procs(os.geteuid(), proc_root)
    result = machine._mcp(processes, {"user": [], "projects": {}}, proc_root)

    assert result["running"] == {"@playwright/mcp": 1}


def test_agent_stack_share(tmp_path):
    processes = [
        procs.Proc(1, os.geteuid(), "claude", 2048, ()),
        procs.Proc(2, os.geteuid(), "codex", 1024, ()),
        procs.Proc(3, os.geteuid(), "node", 3072, ()),
    ]

    result = machine._agent_stack(processes, 100, tmp_path)

    assert result["rss_mb"] == 6
    assert result["share_of_total"] == 0.06


def test_crontab_lines_never_output(tmp_path, monkeypatch):
    sample = canary("generic_assignment", seed=453)
    executable = tmp_path / "crontab"
    executable.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' '0 * * * * echo ok' "
        f"'5 * * * * curl -u user:{sample} service.invalid backup' "
        "'@daily echo done'\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(backups, "VAR_BACKUPS", tmp_path / "missing")

    result = backups.collect_backups(_context(tmp_path))
    rendered = json.dumps(result)

    assert result["cron_entries"] == 3
    assert result["cron_backup_like"] == 1
    assert "curl" not in rendered
    assert all(fragment not in rendered for fragment in fragments(sample))


def test_settings_env_names_only(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    sample = canary("generic_assignment", seed=454)
    (home / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "permissions": {"allow": ["a", "b", "c"]},
                "env": {"TOKEN": sample},
            }
        ),
        encoding="utf-8",
    )

    result = settings.collect_claude_settings(_context(home))
    rendered = json.dumps(result)

    assert result["allow_rules"] == 3
    assert result["env_keys"] == ["TOKEN"]
    assert all(fragment not in rendered for fragment in fragments(sample))


def test_mcp_declared(tmp_path):
    home = tmp_path / "home"
    root = home / "projects" / "demo"
    root.mkdir(parents=True)
    (home / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {"playwright": {}},
                "projects": {str(root): {"mcpServers": {"supabase": {}}}},
            }
        ),
        encoding="utf-8",
    )
    (home / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"filesystem": {}}}), encoding="utf-8"
    )
    (root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"github-mcp": {}}}), encoding="utf-8"
    )

    result = settings.collect_declared_mcp(_context(home, [root]))

    assert result["user"] == ["filesystem", "playwright"]
    assert result["projects"] == {str(root): ["github-mcp", "supabase"]}


def test_disk_home_top_and_large(tmp_path):
    home = tmp_path / "home"
    data = home / "data"
    data.mkdir(parents=True)
    (data / "allocated.bin").write_bytes(b"x" * (3 * 1024 * 1024))
    large = home / "recording.bin"
    with large.open("wb") as stream:
        stream.truncate(250 * 1024 * 1024)
    proc_root = tmp_path / "proc"
    proc_root.mkdir()

    result = disk.collect_disk(_context(home), [], proc_root)

    assert result["home_top"][0]["name"] == "data"
    assert result["large_files"][0]["path"] == "~/recording.bin"
    assert result["large_files"][0]["bytes"] == 250 * 1024 * 1024


def test_disk_used_pct_like_df(tmp_path, monkeypatch):
    gib = 1024 ** 3
    usage = type(
        "DiskUsage",
        (),
        {"total": 100 * gib, "used": 80 * gib, "free": 10 * gib},
    )()
    monkeypatch.setattr(disk.shutil, "disk_usage", lambda path: usage)

    result = disk._filesystems(_context(tmp_path))

    assert result[0]["used_pct"] == 88.9
    assert result[0]["reserved_gb"] == 10.0


def test_disk_partial_on_deadline(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "data").mkdir()
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    ctx = _context(home, deadline=time.time() - 1)

    result = disk.collect_disk(ctx, [], proc_root)

    assert result["home_partial"] is True


def test_projects_counts(tmp_path):
    home = tmp_path / "home"
    project_a = home / "projects" / "a"
    project_b = home / "projects" / "b"
    project_a.mkdir(parents=True)
    project_b.mkdir()
    (project_a / "CLAUDE.md").write_text("# instructions\n", encoding="utf-8")

    result = machine._projects(_context(home))

    assert result["count"] == 2
    assert result["with_claude_md"] == 1
    assert result["without_both"] == ["b"]


def test_missing_files_null(tmp_path, monkeypatch):
    proc_root = tmp_path / "proc"
    cgroup_root = tmp_path / "cgroup"
    proc_root.mkdir()
    cgroup_root.mkdir()
    monkeypatch.setattr(cgroup, "SYSTEMD_SYSTEM_ROOT", tmp_path / "systemd")

    memory = machine._memory(proc_root)
    limits = cgroup.user_slice_limits(os.geteuid(), cgroup_root)

    assert memory["total_mb"] is None
    assert memory["zram"] is None
    assert limits["memory_max_mb"] is None
    assert limits["events_high"] is None


def test_schema_valid(run_collect, tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    result = run_collect("--root", root, "--only", "machine")

    assert result.rc == 0
    validate(result.data)
