from pathlib import Path
import time
from types import SimpleNamespace

from envaudit.arch.context import ArchContext, TreeView
from envaudit.core.context import Context, Flags
from envaudit.core.worktrees import is_linked_worktree, linked_worktree_children
from envaudit.sections import architecture, secrets

from .arch_builders import (
    isolated_runtime,
    make_linked_worktrees,
    write_systemctl_stub,
)
from .canaries import canary


def _context(home: Path, roots: list[Path], *, arch_seconds: int = 90) -> Context:
    started = time.time()
    return Context(
        flags=Flags(arch_root_seconds=arch_seconds),
        home=home,
        roots=roots,
        started_at=started,
        deadline=started + 300,
    )


def test_linked_worktree_detected_without_git(tmp_path, monkeypatch):
    repo, worktrees = make_linked_worktrees(
        tmp_path / "source", tmp_path / "linked", count=1
    )

    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("git must not be called")

    monkeypatch.setattr("envaudit.core.runner.run", unexpected_run)

    assert is_linked_worktree(worktrees[0]) is True
    assert is_linked_worktree(repo) is False
    assert linked_worktree_children(tmp_path / "linked") == 1


def test_container_of_worktrees_not_a_root(fake_home, tmp_path, run_collect):
    container = fake_home / "projects" / "linked"
    make_linked_worktrees(tmp_path / "source", container)
    regular = fake_home / "projects" / "regular"
    regular.mkdir()

    result = run_collect("--only", "no-such-section")

    assert result.rc == 0
    assert result.data["roots"] == [{"path": str(regular), "exists": True}]
    assert {
        "section": "roots",
        "reason": "linked_worktree",
        "details": "linked: 3 рабочих копий",
    } in result.data["skipped"]
    assert result.data["host"]["linked_worktrees_skipped"] == 3


def test_explicit_root_is_respected(fake_home, tmp_path, run_collect):
    container = fake_home / "projects" / "linked"
    make_linked_worktrees(tmp_path / "source", container)

    result = run_collect(
        "--root", container, "--only", "no-such-section"
    )

    assert result.rc == 0
    assert result.data["roots"] == [{"path": str(container), "exists": True}]
    assert result.data["host"]["linked_worktrees_skipped"] == 0
    assert not any(
        item["reason"] == "linked_worktree"
        for item in result.data["skipped"]
    )


def test_walks_skip_worktrees(tmp_path):
    container = tmp_path / "linked"
    _, worktrees = make_linked_worktrees(
        tmp_path / "source", container, count=1
    )
    (worktrees[0] / "inside.canary").write_text("inside", encoding="utf-8")
    (container / "outside.canary").write_text("outside", encoding="utf-8")
    ctx = _context(tmp_path, [container])
    actx = ArchContext(
        ctx=ctx,
        root=container,
        vcs=False,
        out={},
        rule_inputs={},
        trees={
            "primary": TreeView(
                tree_id="primary",
                mode="filesystem",
                path=container,
                sha=None,
                reason="test",
            )
        },
    )

    entries = actx.files()

    assert [entry.rel for entry in entries] == ["outside.canary"]


def test_home_walk_skips_worktrees(fake_home, tmp_path):
    _, worktrees = make_linked_worktrees(
        tmp_path / "source", fake_home / "linked", count=1
    )
    probe = canary("github_token")
    (fake_home / "outside.canary").write_text(probe, encoding="utf-8")
    (worktrees[0] / "inside.canary").write_text(probe, encoding="utf-8")
    ctx = _context(fake_home, [])

    home, _shell, _config = secrets._scan_home_blocks(
        ctx, fake_home / ".codex"
    )

    assert home["files_with_matches"] == 1
    assert home["excluded_worktrees"] == 1


def test_runtime_unit_in_worktree_still_reported(
    fake_home, tmp_path, run_collect, isolated_runtime
):
    root = fake_home / "projects" / "linked"
    _, worktrees = make_linked_worktrees(
        tmp_path / "source", root, count=1
    )
    entry = worktrees[0] / "app.py"
    write_systemctl_stub(
        isolated_runtime,
        {
            "linked.timer": "[Timer]\nOnCalendar=hourly\n",
            "linked.service": (
                "[Service]\n"
                f"WorkingDirectory={worktrees[0]}\n"
                f"ExecStart=/usr/bin/python3 {entry}\n"
            ),
        },
    )

    result = run_collect("--only", "architecture", "--root", root)
    arch = result.data["sections"]["architecture"][str(root.resolve())]

    assert arch["rule_inputs"]["I1"]["live_units"] == 1
    assert arch["runtime"]["live_units"][0]["entry"].endswith("app.py")


def test_arch_per_root_budget(tmp_path, monkeypatch):
    first = tmp_path / "slow"
    second = tmp_path / "fast"
    first.mkdir()
    second.mkdir()

    def slow_check(actx):
        if actx.root == first:
            time.sleep(5)
        actx.out["slow_check_finished"] = True

    def final_check(actx):
        actx.out["final_check_finished"] = True

    checks = [
        SimpleNamespace(KEY="slow", ORDER=1, run=slow_check),
        SimpleNamespace(KEY="final", ORDER=2, run=final_check),
    ]
    monkeypatch.setattr(architecture, "discover_checks", lambda: checks)
    ctx = _context(tmp_path, [first, second], arch_seconds=1)

    result = architecture.collect(ctx)

    assert str(first.resolve()) not in result
    assert result[str(second.resolve())]["final_check_finished"] is True
    assert {
        "section": "architecture",
        "reason": "budget",
        "details": str(first),
    } in ctx.skipped


def test_arch_budget_starts_before_repo_check(tmp_path, monkeypatch):
    first = tmp_path / "slow"
    second = tmp_path / "fast"
    first.mkdir()
    second.mkdir()

    def slow_repo_check(root):
        if root == first:
            time.sleep(5)
        return False

    def finish(actx):
        actx.out["finished"] = True

    checks = [SimpleNamespace(KEY="finish", ORDER=1, run=finish)]
    monkeypatch.setattr(architecture, "discover_checks", lambda: checks)
    monkeypatch.setattr(architecture, "is_git_repo", slow_repo_check)
    ctx = _context(tmp_path, [first, second], arch_seconds=1)

    result = architecture.collect(ctx)

    assert str(first.resolve()) not in result
    assert result[str(second.resolve())]["finished"] is True
    assert {
        "section": "architecture",
        "reason": "budget",
        "details": str(first),
    } in ctx.skipped
