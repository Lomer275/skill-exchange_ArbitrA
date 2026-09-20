import os
from pathlib import Path
import sys
import time

import pytest

from envaudit.core import controls
from envaudit.core.context import Context, Flags
from envaudit.core.dates import status_date
from envaudit.core.runner import git, is_git_repo, run, stream_lines
from envaudit.core.walk import iter_files, read_limited


def _context(home: Path, root: Path | None = None) -> Context:
    started = time.time()
    return Context(Flags(), home, [root or home], started, started + 300)


def _git_init(path: Path) -> None:
    result = run(["git", "init", "-q", str(path)])
    assert result.rc == 0


def test_git_safe_config(tmp_path):
    repo = tmp_path / "repo"
    _git_init(repo)
    result = git(repo, "config", "--get", "core.hooksPath")
    assert result.rc == 0
    assert result.stdout.strip() == b"/dev/null"


def test_git_status_no_index_write(tmp_path):
    repo = tmp_path / "repo"
    _git_init(repo)
    (repo / "tracked.txt").write_text("tracked", encoding="utf-8")
    assert run(["git", "-C", str(repo), "add", "tracked.txt"]).rc == 0
    index = repo / ".git" / "index"
    before = index.stat().st_mtime_ns
    result = git(repo, "status", "--short")
    assert result.rc == 0
    assert index.stat().st_mtime_ns == before


def test_is_git_repo_stub(tmp_path):
    path = tmp_path / "stub"
    (path / ".git" / "info").mkdir(parents=True)
    (path / ".git" / "info" / "exclude").write_text("", encoding="utf-8")
    assert is_git_repo(path) is False
    _git_init(path)
    assert is_git_repo(path) is True


def test_run_not_found_and_timeout():
    missing = run(["no-such-bin-xyz"])
    assert missing.error_kind == "not_found"
    timed_out = run(["sleep", "5"], timeout=0.1)
    assert timed_out.timed_out is True
    assert timed_out.rc is None
    assert timed_out.error_kind == "timeout"


def test_stream_lines_large():
    count = 200_000
    code = "import sys; [sys.stdout.write(str(i) + chr(10)) for i in range(%d)]" % count
    lines = list(stream_lines([sys.executable, "-c", code], timeout=30))
    assert len(lines) == count
    assert lines[0] == b"0\n"
    assert lines[-1] == f"{count - 1}\n".encode()


def test_walk_excludes_and_symlinks(tmp_path):
    home = tmp_path / "home"
    root = home / "projects" / "root"
    root.mkdir(parents=True)
    for directory in ("node_modules", ".venv", ".git"):
        (root / directory).mkdir()
        (root / directory / "excluded.txt").write_text("x", encoding="utf-8")
    (root / "included.txt").write_text("ok", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (root / "outside-link").symlink_to(outside)
    backup = home / "audit-2026-09-17" / "backup"
    backup.mkdir(parents=True)
    (backup / "file.txt").write_text("backup", encoding="utf-8")

    entries = list(iter_files(home, _context(home, root), "walk"))
    rels = {entry.rel for entry in entries}
    assert "projects/root/included.txt" in rels
    assert not any("excluded.txt" in rel for rel in rels)
    assert not any(rel.startswith("audit-") for rel in rels)
    link = next(entry for entry in entries if entry.rel.endswith("outside-link"))
    assert link.is_symlink is True
    assert link.symlink_inside_root is False
    assert read_limited(link, 1024) is None


def test_walk_permission_skip(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can read mode 000 directories")
    root = tmp_path / "root"
    blocked = root / "blocked"
    blocked.mkdir(parents=True)
    blocked.chmod(0)
    ctx = _context(tmp_path, root)
    try:
        list(iter_files(root, ctx, "walk"))
    finally:
        blocked.chmod(0o700)
    assert any(item["reason"] == "permission" for item in ctx.skipped)


def test_status_date_sources(tmp_path):
    named = tmp_path / "HANDOFF_2026-09-08.md"
    named.write_text("", encoding="utf-8")
    headed = tmp_path / "HANDOFF.md"
    headed.write_text("", encoding="utf-8")
    plain = tmp_path / "STATUS.md"
    plain.write_text("", encoding="utf-8")
    named_info = status_date(named)
    headed_info = status_date(headed, "# Статус на 11.08.2026")
    plain_info = status_date(plain)
    assert (named_info.date, named_info.source, named_info.trust) == ("2026-09-08", "name", "high")
    assert (headed_info.date, headed_info.source, headed_info.trust) == ("2026-08-11", "header", "medium")
    assert plain_info.source == "mtime"
    assert plain_info.trust == "low"


def test_positive_control_pass_fail_cleanup(tmp_path, monkeypatch):
    created = []
    original = controls.tempfile.mkdtemp

    def make_temp(*, prefix):
        path = original(prefix=prefix, dir=tmp_path)
        created.append(Path(path))
        return path

    monkeypatch.setattr(controls.tempfile, "mkdtemp", make_temp)
    ctx = _context(tmp_path)

    def build(path):
        (path / "probe").write_text("x", encoding="utf-8")

    assert controls.positive_control("x", "pass", ctx, build, lambda path: len(list(path.iterdir()))) == "pass"
    assert controls.positive_control("x", "fail", ctx, build, lambda path: 0) == "fail"
    assert created and all(not path.exists() for path in created)
