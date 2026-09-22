import json
import time

from envaudit.core.context import Context, Flags
from envaudit.sections import secrets

from .canaries import canary, fragments


def _section(result):
    return result.data["sections"]["secrets"]


def test_cloud_dirs_and_transcripts_excluded(run_collect, fake_home, tmp_path):
    paths = [
        fake_home / "OneDrive-x" / "f",
        fake_home / ".claude" / "projects" / "p" / "s.jsonl",
        fake_home / ".cache" / "f",
    ]
    for index, path in enumerate(paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canary("github_token", index), encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    section = _section(run_collect("--root", root, "--only", "secrets"))
    assert section["home"]["files_with_matches"] == 0


def test_shell_history_and_config(run_collect, fake_home, tmp_path):
    (fake_home / ".bash_history").write_text(canary("openai_key"), encoding="utf-8")
    config = fake_home / ".config" / "app" / "c.ini"
    config.parent.mkdir(parents=True)
    config.write_text(canary("jwt"), encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    section = _section(run_collect("--root", root, "--only", "secrets"))
    assert section["shell_history"]["with_matches"] == 1
    assert section["config_dir"]["files_with_matches"] == 1


def test_external_access_names_only(run_collect, fake_home, tmp_path):
    credential_text = canary("github_token")
    hosts = fake_home / ".config" / "gh" / "hosts.yml"
    hosts.parent.mkdir(parents=True)
    hosts.write_text(
        "github.com:\n  oauth_token: " + credential_text,
        encoding="utf-8",
    )
    docker = fake_home / ".docker" / "config.json"
    docker.parent.mkdir()
    docker.write_text(
        json.dumps({"auths": {"registry.invalid": {"auth": credential_text}}}),
        encoding="utf-8",
    )
    root = tmp_path / "root"
    root.mkdir()
    result = run_collect("--root", root, "--only", "secrets")
    access = _section(result)["external_access"]
    assert access["gh_hosts"] == ["github.com"]
    assert access["docker_registries"] == ["registry.invalid"]
    assert all(part not in result.stdout for part in fragments(credential_text))


def test_home_budget_preserves_later_blocks(fake_home):
    probe = canary("github_token")
    (fake_home / ".bash_history").write_text(probe, encoding="utf-8")
    config = fake_home / ".config" / "app" / "settings.ini"
    config.parent.mkdir(parents=True)
    config.write_text(probe, encoding="utf-8")
    started = time.time()
    ctx = Context(Flags(), fake_home, [], started, started + 300)

    home, shell, config_dir = secrets._scan_home_blocks(
        ctx,
        fake_home / ".codex",
        home_deadline=started - 1,
    )

    assert home["truncated"] is True
    assert home["stopped_at"] == "."
    expected = {"section": "secrets", "reason": "budget", "details": "home"}
    assert home["files_scanned"] == 0
    assert ctx.skipped.count(expected) == 1
    assert shell["with_matches"] == 1
    assert config_dir["files_with_matches"] == 1


def test_home_walk_order_is_deterministic(fake_home, monkeypatch):
    (fake_home / "z.txt").write_text("z", encoding="utf-8")
    (fake_home / "a.txt").write_text("a", encoding="utf-8")
    nested = fake_home / "middle" / "b.txt"
    nested.parent.mkdir()
    nested.write_text("b", encoding="utf-8")
    seen = []

    def record_scan(data, counter, *, path_rel, is_fixture, include_generic):
        seen.append(path_rel)
        return 0

    monkeypatch.setattr(secrets, "scan_bytes", record_scan)
    started = time.time()
    ctx = Context(Flags(), fake_home, [], started, started + 300)

    secrets._scan_tree_summary(
        fake_home,
        ctx,
        home_prefix=True,
        include_generic=False,
    )

    assert seen == ["~/a.txt", "~/z.txt", "~/middle/b.txt"]


def test_home_priority_and_not_reached(fake_home, monkeypatch):
    for dirname in (".aaa", ".claude", "Downloads"):
        directory = fake_home / dirname
        directory.mkdir(exist_ok=True)
        (directory / "probe.txt").write_text(dirname, encoding="utf-8")
    seen = []
    started = time.time()
    ctx = Context(Flags(), fake_home, [], started, started + 300)

    def stop_after_first(data, counter, *, path_rel, is_fixture, include_generic):
        seen.append(path_rel)
        ctx.deadline = time.time() - 1
        return 0

    monkeypatch.setattr(secrets, "scan_bytes", stop_after_first)
    summary = secrets._scan_tree_summary(
        fake_home,
        ctx,
        home_prefix=True,
        include_generic=False,
        budget_details="home",
    )

    assert seen == ["~/.claude/probe.txt"]
    assert summary["truncated"] is True
    assert {".aaa", "Downloads"} <= set(summary["not_reached"])
    assert len(summary["not_reached"]) <= 30
