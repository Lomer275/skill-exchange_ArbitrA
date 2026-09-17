from pathlib import Path

from envaudit.core.runner import run

from .canaries import canary


def _git(repo: Path, *args: str) -> None:
    assert run(["git", "-C", str(repo), *args]).rc == 0


def _repo(path: Path) -> None:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "a")
    _git(path, "config", "user.email", "a@a")


def _root(result, repo: Path):
    return result.data["sections"]["secrets"]["roots"][str(repo)]


def test_head_and_history(run_collect, tmp_path):
    repo = tmp_path / "repo"
    _repo(repo)
    first = canary("github_token", 1)
    second = canary("github_token", 2)
    target = repo / "value.txt"
    target.write_text(first, encoding="utf-8")
    _git(repo, "add", "value.txt")
    _git(repo, "commit", "-qm", "one")
    target.unlink()
    _git(repo, "add", "-u")
    _git(repo, "commit", "-qm", "two")
    target.write_text(second, encoding="utf-8")
    _git(repo, "add", "value.txt")
    _git(repo, "commit", "-qm", "three")
    item = _root(run_collect("--root", repo, "--only", "secrets"), repo)["patterns"]["github_token"]
    assert item["head_files"] == 1
    assert item["history_commits"] >= 2
    assert item["history_distinct"] == 2


def test_untracked_not_ignored(run_collect, tmp_path):
    repo = tmp_path / "repo"
    _repo(repo)
    (repo / "base").write_text("x", encoding="utf-8")
    _git(repo, "add", "base")
    _git(repo, "commit", "-qm", "base")
    (repo / "loose.txt").write_text(canary("anthropic_key"), encoding="utf-8")
    item = _root(run_collect("--root", repo, "--only", "secrets"), repo)["patterns"]["anthropic_key"]
    assert item["worktree_files"] == 1


def test_cyrillic_and_spaces_paths(run_collect, tmp_path):
    repo = tmp_path / "repo"
    _repo(repo)
    name = "Дубли email (копия).py"
    (repo / name).write_text(canary("jwt"), encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-qm", "unicode")
    item = _root(run_collect("--root", repo, "--only", "secrets"), repo)["patterns"]["jwt"]
    assert item["head_files"] == 1
    assert name in item["paths_sample"]

