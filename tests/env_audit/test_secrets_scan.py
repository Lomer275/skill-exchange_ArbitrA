import io
import json
from pathlib import Path
import tarfile
import time

from envaudit.core import patterns
from envaudit.core.context import Context, Flags
from envaudit.core.dockerignore import load_matcher
from envaudit.core.runner import run
from envaudit.secrets.scan import Counter, scan_bytes
from envaudit.sections import secrets

from .canaries import CANARY_CLASSES, canary, fragments


def _section(result):
    assert result.data is not None
    return result.data["sections"]["secrets"]


def _root(section, root: Path):
    return section["roots"][str(root)]


def _git(repo: Path, *args: str) -> None:
    assert run(["git", "-C", str(repo), *args]).rc == 0


def test_each_class_in_tree_no_vcs(run_collect, tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    for index, cls in enumerate(CANARY_CLASSES):
        (root / f"f{index}.txt").write_text(canary(cls, index), encoding="utf-8")
    result = run_collect("--root", root, "--only", "secrets")
    view = _root(_section(result), root)
    for cls in CANARY_CLASSES:
        if cls == "generic_assignment":
            assert cls not in view["patterns"]
        else:
            assert view["patterns"][cls]["worktree_files"] == 1
    assert any(item["reason"] == "no_vcs" for item in result.data["skipped"])


def test_fake_filtered(run_collect, tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    fake = "s" + "k-" + "abcdefghijklmnopqrstuvwxyz"
    (root / "f.txt").write_text(fake, encoding="utf-8")
    view = _root(_section(run_collect("--root", root, "--only", "secrets")), root)
    assert view["patterns"]["openai_key"]["fake_filtered"] == 1
    assert view["patterns"]["openai_key"]["worktree_files"] == 0


def test_distinct_values(run_collect, tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    first = canary("openai_key", 1)
    second = canary("openai_key", 2)
    for index in range(5):
        (root / f"a{index}").write_text(first, encoding="utf-8")
    (root / "b").write_text(second, encoding="utf-8")
    view = _root(_section(run_collect("--root", root, "--only", "secrets")), root)
    item = view["patterns"]["openai_key"]
    assert item["worktree_files"] == 6
    assert item["distinct"] == 2
    assert item["user_ids"] == []


def test_fixture_path(run_collect, tmp_path):
    root = tmp_path / "plain"
    target = root / "tests" / "test_x.py"
    target.parent.mkdir(parents=True)
    target.write_text(canary("github_token"), encoding="utf-8")
    item = _root(_section(run_collect("--root", root, "--only", "secrets")), root)["patterns"]["github_token"]
    assert item["test_fixture_files"] == 1
    assert item["worktree_files"] == 0


def test_webhook_user_ids(run_collect, tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    first = canary("bitrix_webhook", 31).replace("/30662/", "/30351/")
    second = canary("bitrix_webhook", 62)
    (root / "hooks.txt").write_text(first + "\n" + second, encoding="utf-8")
    item = _root(_section(run_collect("--root", root, "--only", "secrets")), root)["patterns"]["bitrix_webhook"]
    assert item["user_ids"] == [30351, 30662]


def test_context_file_critical_input(run_collect, fake_home, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "CLAUDE.md").write_text(canary("github_token"), encoding="utf-8")
    memory = fake_home / ".claude" / "projects" / "p" / "memory" / "card.md"
    memory.parent.mkdir(parents=True)
    memory.write_text(canary("jwt"), encoding="utf-8")
    kinds = {item["kind"] for item in _section(run_collect("--root", root, "--only", "secrets"))["context_files"]}
    assert {"claude_md", "memory"} <= kinds


def test_context_files_ignore_generic_assignment(run_collect, fake_home, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "CLAUDE.md").write_text(
        canary("generic_assignment"),
        encoding="utf-8",
    )
    section = _section(run_collect("--root", root, "--only", "secrets"))
    assert section["context_files"] == []
    assert section["context_generic_assignment"] == {"files": 1, "matches": 1}


def test_generic_assignment_scope(run_collect, fake_home, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "root.txt").write_text(
        canary("generic_assignment", 1),
        encoding="utf-8",
    )
    (fake_home / "home.txt").write_text(
        canary("generic_assignment", 2),
        encoding="utf-8",
    )
    (fake_home / ".bash_history").write_text(
        canary("generic_assignment", 3),
        encoding="utf-8",
    )
    config = fake_home / ".config" / "app" / "settings.ini"
    config.parent.mkdir(parents=True)
    config.write_text(canary("generic_assignment", 4), encoding="utf-8")

    section = _section(run_collect("--root", root, "--only", "secrets"))

    assert section["generic_assignment_scope"] == [
        "context_files",
        "agent_configs",
        "shell_history",
        "config_dir",
    ]
    assert "generic_assignment" not in _root(section, root)["patterns"]
    assert "generic_assignment" not in section["home"]["by_class"]
    assert section["shell_history"]["by_class"]["generic_assignment"]["files"] == 1
    assert section["config_dir"]["by_class"]["generic_assignment"]["files"] == 1


def test_agent_config_env_allow_bak(run_collect, fake_home, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    live = {"env": {"X": canary("openai_key")}}
    backup = {"permissions": {"allow": ["Bash(curl " + canary("bitrix_webhook") + ")"]}}
    (fake_home / ".claude" / "settings.json").write_text(json.dumps(live), encoding="utf-8")
    (fake_home / ".claude" / "settings.json.bak-0701").write_text(json.dumps(backup), encoding="utf-8")
    configs = _section(run_collect("--root", root, "--only", "secrets"))["agent_configs"]
    by_name = {Path(item["path"]).name: item for item in configs}
    assert by_name["settings.json"]["env_keys_with_secret"] == 1
    assert by_name["settings.json.bak-0701"]["is_backup"] is True
    assert by_name["settings.json.bak-0701"]["allow_rules_with_secret"] == 1


def test_agent_config_generic_assignment_is_counter_only(
    run_collect, fake_home, tmp_path
):
    root = tmp_path / "project"
    root.mkdir()
    path = fake_home / ".claude" / "settings.json"
    path.write_text(
        json.dumps({"note": canary("generic_assignment")}),
        encoding="utf-8",
    )
    section = _section(run_collect("--root", root, "--only", "secrets"))
    item = next(value for value in section["agent_configs"] if value["path"].endswith("settings.json"))
    assert item["other_matches"] == 0
    assert "generic_assignment" not in item["classes"]
    assert section["agent_configs_generic_assignment"] == {"files": 1, "matches": 1}


def test_env_like_files(run_collect, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "a")
    _git(root, "config", "user.email", "a@a")
    value = canary("openai_key")
    (root / ".gitignore").write_text(".env\n", encoding="utf-8")
    (root / ".env").write_text(value, encoding="utf-8")
    (root / ".env.bak-1").write_text(value, encoding="utf-8")
    (root / ".env.ci").write_text(canary("github_token"), encoding="utf-8")
    workflow = root / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("source .env.ci", encoding="utf-8")
    _git(root, "add", ".gitignore", ".env.bak-1", ".env.ci", ".github/workflows/ci.yml")
    _git(root, "commit", "-qm", "files")
    files = _root(_section(run_collect("--root", root, "--only", "secrets")), root)["env_like_files"]
    by_name = {item["path"]: item for item in files}
    assert by_name[".env"]["ignored"] is True
    assert by_name[".env.bak-1"]["identical_to_ignored_env"] is True
    assert by_name[".env.ci"]["ci_referenced"] is True


def test_secrets_dir_modes(run_collect, tmp_path):
    root = tmp_path / "plain"
    directory = root / ".secrets"
    directory.mkdir(parents=True, mode=0o700)
    item = directory / "x"
    item.write_text(canary("jwt"), encoding="utf-8")
    item.chmod(0o644)
    info = _root(_section(run_collect("--root", root, "--only", "secrets")), root)["secrets_dir"]
    assert info["mode"] == "0700"
    assert info["files_wider_than_600"] == 1


def test_archive_members(run_collect, tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    data = canary("openai_key").encode()
    with tarfile.open(root / "deploy.tar.gz", "w:gz") as archive:
        info = tarfile.TarInfo(".env")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    archives = _root(_section(run_collect("--root", root, "--only", "secrets")), root)["archives"]
    assert archives == [{"path": "deploy.tar.gz", "tracked": None, "secret_members": 1}]


def test_dockerignore_context(run_collect, tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "Dockerfile").write_text("FROM scratch\nCOPY . .\n", encoding="utf-8")
    (root / ".dockerignore").write_text("*.log\n", encoding="utf-8")
    (root / ".env").write_text(canary("openai_key"), encoding="utf-8")
    context = _root(_section(run_collect("--root", root, "--only", "secrets")), root)["build_context"]
    assert ".env" in context["sensitive_in_context"]


def test_dockerignore_supported_subset(tmp_path):
    (tmp_path / ".dockerignore").write_text(
        "**/.env\nlogs/\n!logs/keep.txt\n/root.txt\n*.tmp\n",
        encoding="utf-8",
    )
    matcher = load_matcher(tmp_path)
    assert matcher is not None
    assert matcher(".env") is True
    assert matcher("nested/.env") is True
    assert matcher("logs/a.txt") is True
    assert matcher("logs/keep.txt") is False
    assert matcher("root.txt") is True
    assert matcher("nested/root.txt") is False
    assert matcher("nested/a.tmp") is True


def test_no_values_in_output(run_collect, tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    values = [canary(cls, index + 100) for index, cls in enumerate(CANARY_CLASSES)]
    (root / "all.txt").write_text("\n".join(values), encoding="utf-8")
    result = run_collect("--root", root, "--only", "secrets")
    assert result.rc == 0
    for value in values:
        assert all(part not in result.stdout for part in fragments(value))


def test_prefilter_skips_regex(monkeypatch):
    calls = 0
    original = patterns.find

    def counted(data, **kwargs):
        nonlocal calls
        calls += 1
        return original(data, **kwargs)

    monkeypatch.setattr(patterns, "find", counted)
    counter = Counter()
    assert not scan_bytes(
        b"ordinary prose with no signals",
        counter,
        path_rel="plain.txt",
        is_fixture=False,
        include_generic=True,
    )
    assert calls == 0


def test_timings_present(run_collect, tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    timings = _section(run_collect("--root", root, "--only", "secrets"))["timings_s"]
    assert set(timings) == {
        "positive_controls",
        "context_files",
        "agent_configs",
        "roots",
        "home",
        "shell_history",
        "config_dir",
        "storage",
        "ssh_keys",
        "external",
    }
    assert all(value >= 0 and value == round(value, 2) for value in timings.values())


def test_positive_control_fail_nulls_block(tmp_path, monkeypatch):
    started = time.time()
    ctx = Context(Flags(), tmp_path, [tmp_path], started, started + 300, shared={"host": {"codex_home": str(tmp_path / ".codex")}})
    monkeypatch.setattr(patterns, "find", lambda data, **kwargs: [])
    section = secrets.collect(ctx)
    assert section["positive_controls"]["tree"] == "fail"
    assert section["roots"] is None
    assert {"section": "secrets", "kind": "positive_control_failed:tree"} in ctx.errors
