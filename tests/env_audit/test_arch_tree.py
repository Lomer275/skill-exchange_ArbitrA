import os
from pathlib import Path
import subprocess
import tempfile

from .arch_builders import (
    _git,
    isolated_runtime,
    make_bare,
    make_repo,
    write_crontab_stub,
)
from .schema_check import validate


def _arch(result, root: Path) -> dict:
    assert result.rc == 0, result.stdout
    validate(result.data)
    return result.data["sections"]["architecture"][str(root.resolve())]


def test_no_vcs_stub_git(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "project"
    (root / ".git" / "info").mkdir(parents=True)
    (root / ".git" / "info" / "exclude").write_text("", encoding="utf-8")

    result = run_collect("--only", "architecture", "--root", root)
    arch = _arch(result, root)

    assert arch["tree"]["vcs"] == {"present": False, "reason": "stub_git_dir"}
    assert arch["tree"]["analysed"][0]["mode"] == "filesystem"
    assert any(
        item["section"] == "architecture" and item["reason"] == "no_vcs"
        for item in result.data["skipped"]
    )


def test_clean_checkout_worktree(tmp_path: Path, run_collect) -> None:
    remote = make_bare(tmp_path / "origin.git")
    root = make_repo(tmp_path / "project", {"app.py": "print('ok')\n"}, remote=remote)

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["tree"]["analysed"][0]["mode"] == "worktree"
    assert arch["tree"]["analysed"][0]["reason"] == "1.2:clean"
    assert arch["tree"]["ahead"] == 0
    assert arch["tree"]["ls_remote_ok"] is True


def test_behind_uses_archive(tmp_path: Path, run_collect) -> None:
    remote = make_bare(tmp_path / "origin.git")
    root = make_repo(tmp_path / "project", {"app.py": "value = 1\n"}, remote=remote)
    upstream = tmp_path / "upstream"
    subprocess.run(
        ["git", "clone", str(remote), str(upstream)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(upstream, "config", "user.name", "Env Audit Test")
    _git(upstream, "config", "user.email", "env-audit@example.invalid")
    for value in (2, 3):
        (upstream / "app.py").write_text(f"value = {value}\n", encoding="utf-8")
        _git(upstream, "add", "app.py")
        _git(upstream, "commit", "-m", f"change-{value}")
    _git(upstream, "push", "origin", "main")
    _git(root, "fetch", "origin")
    before = set(Path(tempfile.gettempdir()).glob("env-audit-*"))

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    primary = arch["tree"]["analysed"][0]
    assert primary["mode"] == "archive"
    assert primary["sha"] == arch["tree"]["origin_default_sha"]
    assert set(Path(tempfile.gettempdir()).glob("env-audit-*")) == before


def test_live_unit_uses_worktree(tmp_path: Path, run_collect) -> None:
    remote = make_bare(tmp_path / "origin.git")
    root = make_repo(tmp_path / "project", {"run.py": "print('local')\n"}, remote=remote)
    upstream = tmp_path / "upstream"
    subprocess.run(
        ["git", "clone", str(remote), str(upstream)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(upstream, "config", "user.name", "Env Audit Test")
    _git(upstream, "config", "user.email", "env-audit@example.invalid")
    (upstream / "run.py").write_text("print('remote')\n", encoding="utf-8")
    _git(upstream, "add", "run.py")
    _git(upstream, "commit", "-m", "remote change")
    _git(upstream, "push", "origin", "main")
    _git(root, "fetch", "origin")
    bin_dir = tmp_path / "bin"
    cron_line = f"*/5 * * * * cd {root} && python3 run.py"
    write_crontab_stub(bin_dir, [cron_line])

    result = run_collect(
        "--only",
        "architecture",
        "--root",
        root,
        env_extra={"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]},
    )
    arch = _arch(result, root)

    assert arch["tree"]["analysed"][0]["mode"] == "worktree"
    assert arch["tree"]["analysed"][0]["reason"] == "1.2:live_unit"
    assert cron_line not in result.stdout


def test_local_branch_plus20_alt(tmp_path: Path, run_collect) -> None:
    remote = make_bare(tmp_path / "origin.git")
    root = make_repo(tmp_path / "project", {"app.py": "value = 1\n"}, remote=remote)
    _git(root, "switch", "-c", "local-large")
    (root / "extra.py").write_text("\n".join(f"value_{i} = {i}" for i in range(30)) + "\n", encoding="utf-8")
    _git(root, "add", "extra.py")
    _git(root, "commit", "-m", "local expansion")
    _git(root, "switch", "main")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert any(item["tree_id"] == "alt" for item in arch["tree"]["analysed"])
    branch = next(item for item in arch["tree"]["local_branches"] if item["name"] == "local-large")
    assert branch["local_only"] is True


def test_crlf_only(tmp_path: Path, run_collect) -> None:
    root = make_repo(tmp_path / "project", {"app.py": b"one\ntwo\n"})
    (root / "app.py").write_bytes(b"one\r\ntwo\r\n")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["tree"]["dirty"]["crlf_only_files"] == 1
    assert arch["tree"]["dirty"]["lines_add"] == 0


def test_cyrillic_paths(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "Битрикс (Ирина, dev2)"
    root.mkdir()
    (root / "Дубли email.py").write_text("значение = 1\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["size"]["by_language"]["python"]["files"] == 1
    assert arch["size"]["by_language"]["python"]["lines"] == 1


def test_nested_worktree_excluded(tmp_path: Path, run_collect) -> None:
    root = make_repo(tmp_path / "project", {"app.py": "VALUE = 1\n"})
    nested = root / ".worktrees" / "nested"
    _git(root, "worktree", "add", "-b", "nested-check", str(nested))
    (nested / "Dockerfile.nested").write_text(
        'FROM python:3\nCMD ["python", "nested_app.py"]\n',
        encoding="utf-8",
    )
    (nested / "nested_app.py").write_text("VALUE = 2\n", encoding="utf-8")
    linked = root / "linked-copy"
    linked.mkdir()
    (linked / ".git").write_text(
        "gitdir: /nonexistent/worktree-metadata\n", encoding="utf-8"
    )
    (linked / "Dockerfile.linked").write_text(
        'FROM python:3\nCMD ["python", "linked_app.py"]\n',
        encoding="utf-8",
    )
    (linked / "linked_app.py").write_text("VALUE = 3\n", encoding="utf-8")

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert any(item["path"] == str(nested) for item in arch["tree"]["worktrees"])
    assert arch["classification"]["signals"]["scripts"]["py_files"] == 1
    assert arch["classification"]["subprojects"] == []
    assert arch["runtime"]["anchors"] == []
    assert arch["size"]["by_language"]["python"]["files"] == 1
