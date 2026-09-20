import json
from pathlib import Path
import time

import pytest

from envaudit.core.context import Context, Flags
from envaudit.core.runner import run
from envaudit.sections import regulations

from .canaries import canary, fragments
from .schema_check import validate


def _context(
    home: Path,
    roots: list[Path] | None = None,
    *,
    profile: str = "both",
    codex_version: str | None = None,
) -> Context:
    started = time.time()
    ctx = Context(Flags(), home, roots or [], started, started + 300)
    ctx.shared["host"] = {
        "profile": profile,
        "codex_home": str(home / ".codex"),
        "codex_version": codex_version,
    }
    return ctx


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _git(path: Path, *args: str) -> bytes:
    result = run(["git", "-C", str(path), *args])
    assert result.rc == 0
    return result.stdout


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    assert run(["git", "init", "-q", str(path)]).rc == 0
    _git(path, "config", "user.name", "Env Audit Test")
    _git(path, "config", "user.email", "env-audit@example.invalid")


@pytest.fixture(autouse=True)
def _without_docker(monkeypatch):
    original = regulations.runner.which
    monkeypatch.setattr(
        regulations.runner,
        "which",
        lambda name: None if name == "docker" else original(name),
    )


def test_r1_github_marketplace(fake_home):
    _write_json(
        fake_home / ".claude" / "plugins" / "known_marketplaces.json",
        {
            "skill-exchange": {
                "source": {
                    "source": "github",
                    "repo": "Lomer275/skill-exchange_ArbitrA",
                },
                "autoUpdate": True,
                "lastUpdated": "2026-09-10T12:00:00Z",
            },
            "claude-plugins-official": {
                "source": {"source": "github", "repo": "anthropics/claude-plugins-official"}
            },
        },
    )

    section = regulations.collect(_context(fake_home))
    r1 = section["r1_exchange"]
    assert r1["skill_exchange_present"] is True
    assert r1["official_present"] is True
    assert {item["name"]: item["source_kind"] for item in r1["marketplaces"]} == {
        "claude-plugins-official": "github",
        "skill-exchange": "github",
    }
    exchange = next(item for item in r1["marketplaces"] if item["name"] == "skill-exchange")
    assert exchange["auto_update"] is True
    assert exchange["last_updated"] == "2026-09-10"


def test_r1_git_url_source(fake_home, run_collect):
    sample = canary("openai_key", seed=454)
    url = (
        "https" + "://user:" + sample
        + "@github.com/Lomer275/skill-exchange_ArbitrA.git"
    )
    _write_json(
        fake_home / ".claude" / "plugins" / "known_marketplaces.json",
        {
            "skill-exchange": {
                "source": {"source": "git", "url": url},
                "lastUpdated": "2026-09-17T12:00:00Z",
            }
        },
    )

    result = run_collect(
        "--root", fake_home / "projects", "--only", "regulations"
    )
    assert result.rc == 0
    r1 = result.data["sections"]["regulations"]["r1_exchange"]
    exchange = r1["marketplaces"][0]
    assert exchange["source_kind"] == "git"
    assert exchange["source"] == (
        "https://github.com/Lomer275/skill-exchange_ArbitrA.git"
    )
    assert r1["skill_exchange_present"] is True
    assert r1["directory_checkout"] is None
    assert all(fragment not in result.stdout for fragment in fragments(sample))


def test_r1_auto_update_missing_null(fake_home):
    _write_json(
        fake_home / ".claude" / "plugins" / "known_marketplaces.json",
        {
            "skill-exchange": {
                "source": {
                    "source": "github",
                    "repo": "Lomer275/skill-exchange_ArbitrA",
                }
            }
        },
    )

    r1 = regulations.collect(_context(fake_home))["r1_exchange"]
    assert r1["marketplaces"][0]["auto_update"] is None


def test_r1_directory_checkout(fake_home):
    repo = fake_home / "tools" / "skill-exchange_ArbitrA"
    _init_repo(repo)
    (repo / "state.txt").write_text("base", encoding="utf-8")
    _git(repo, "add", "state.txt")
    _git(repo, "commit", "-qm", "base")
    current = _git(repo, "branch", "--show-current").decode().strip()
    _git(repo, "checkout", "-qb", "tracking")
    for number in (1, 2):
        (repo / "state.txt").write_text(str(number), encoding="utf-8")
        _git(repo, "commit", "-qam", f"ahead {number}")
    _git(repo, "checkout", "-q", current)
    _git(repo, "branch", "--set-upstream-to=tracking", current)
    _write_json(
        fake_home / ".claude" / "plugins" / "known_marketplaces.json",
        {
            "skill-exchange": {
                "source": {"source": "directory", "path": str(repo)},
                "autoUpdate": False,
            }
        },
    )

    r1 = regulations.collect(_context(fake_home))["r1_exchange"]
    assert r1["marketplaces"][0]["source_kind"] == "directory"
    assert r1["directory_checkout"]["path"] == "~/tools/skill-exchange_ArbitrA"
    assert r1["directory_checkout"]["is_git"] is True
    assert r1["directory_checkout"]["behind_tracking"] == 2


def test_r2_full_and_partial(fake_home):
    full = fake_home / "projects" / "full"
    full_docs = full / "docs"
    for name in (
        "1. SUP-business requirements",
        "2. SUP-specifications",
        "3. SUP-tasks",
        "4. SUP-guides",
        "5. SUP-unsorted",
        "backlog",
    ):
        (full_docs / name).mkdir(parents=True)
    for name in ("README.md", "SUP-architecture.md", "SUP-CHANGELOG.md", "SUP-HANDOFF.md"):
        (full / name).write_text("", encoding="utf-8")

    partial = fake_home / "projects" / "partial"
    partial_docs = partial / "docs"
    partial_docs.mkdir(parents=True)
    for name in ("CRM-architecture.md", "CRM-CHANGELOG.md", "CRM-HANDOFF.md"):
        (partial_docs / name).write_text("", encoding="utf-8")

    bare = fake_home / "projects" / "bare"
    (bare / ".git").mkdir(parents=True)

    r2 = regulations.collect(_context(fake_home, [full, partial, bare]))["r2_docs"]
    assert r2[str(full)]["prefix"] == "SUP"
    assert set(r2[str(full)]["root_files"].values()) == {"root"}
    assert all(r2[str(full)]["folders"].values())
    assert r2[str(partial)]["prefix"] == "CRM"
    assert r2[str(partial)]["root_files"] == {
        "README.md": None,
        "architecture": "docs",
        "CHANGELOG": "docs",
        "HANDOFF": "docs",
    }
    assert r2[str(bare)]["prefix"] is None
    assert all(value is None for value in r2[str(bare)]["root_files"].values())


def test_r4_url_credentials_stripped(fake_home, run_collect):
    root = fake_home / "projects" / "credential-test"
    _init_repo(root)
    sample = canary("openai_key", seed=453)
    origin = "https" + "://user:" + sample + "@github.com/a/b.git"
    _git(root, "remote", "add", "origin", origin)

    result = run_collect("--root", root, "--only", "regulations")
    assert result.rc == 0
    facts = result.data["sections"]["regulations"]["r4_github"]["roots"][str(root)]
    assert facts["origin_host"] == "github.com"
    assert facts["origin_repo"] == "a/b"
    assert all(fragment not in result.stdout for fragment in fragments(sample))


def test_r4_no_vcs_files_count(fake_home):
    root = fake_home / "projects" / "files"
    (root / "docs").mkdir(parents=True)
    for number in range(5):
        (root / f"file-{number}.txt").write_text("x", encoding="utf-8")

    facts = regulations.collect(_context(fake_home, [root]))["r4_github"]["roots"][str(root)]
    assert facts["vcs"] is False
    assert facts["files"] == 5
    assert facts["has_docs"] is True


def test_r5_team_context_counts(fake_home):
    global_claude = fake_home / ".claude" / "CLAUDE.md"
    global_claude.write_text("<!-- BEGIN team-context -->\n", encoding="utf-8")
    global_codex = fake_home / ".codex" / "AGENTS.md"
    global_codex.parent.mkdir(parents=True)
    global_codex.write_text("<!-- BEGIN team-context -->\n", encoding="utf-8")
    root = fake_home / "projects" / "rules"
    root.mkdir()
    (root / "AGENTS.md").write_text("project rules\n", encoding="utf-8")

    r5 = regulations.collect(_context(fake_home, [root]))["r5_levels"]
    assert r5["global_claude_team_context"] == 1
    assert r5["global_codex_team_context"] == 1
    assert r5["projects"][str(root)]["agents_md_team_context"] == 0


def test_r6_version_compare(fake_home):
    old = regulations.collect(
        _context(fake_home, codex_version="0.145.9")
    )["r6_codex"]
    current = regulations.collect(
        _context(fake_home, codex_version="0.146.0")
    )["r6_codex"]
    assert old["version_at_least_0_146"] is False
    assert current["version_at_least_0_146"] is True


def test_r7_code_without_container(fake_home):
    root = fake_home / "projects" / "service"
    root.mkdir()
    (root / "main.py").write_text("", encoding="utf-8")

    facts = regulations.collect(_context(fake_home, [root]))["r7_docker"]["roots"][str(root)]
    assert facts["has_code"] is True
    assert facts["container_files"] == []


def test_r8_exact_by_frontmatter_name(fake_home):
    memory = fake_home / ".claude" / "projects" / "-home-u-projects-x" / "memory"
    memory.mkdir(parents=True)
    (memory / "arbitrary-note.md").write_text(
        "---\nname: BiTrIx_task-Regulations\n---\n"
        "# Регламент на 2026-08-13\n",
        encoding="utf-8",
    )

    cards = regulations.collect(_context(fake_home))["r8_r10_memory"]
    matches = cards["bitrix_regulation"]
    assert [item["file"] for item in matches["exact"]] == ["arbitrary-note.md"]
    assert matches["exact"][0]["name"] == "BiTrIx_task-Regulations"
    assert matches["exact"][0]["date"] == "2026-08-13"
    assert matches["exact"][0]["date_source"] == "header"
    assert matches["candidates"] == []
    assert matches["candidates_truncated"] is False


def test_r8_noise_files_are_candidates_only(fake_home):
    memory = fake_home / ".claude" / "projects" / "-home-u-projects-x" / "memory"
    memory.mkdir(parents=True)
    for name in (
        "bitrix_box_bak_files_served_as_source.md",
        "bitrix_call_unwraps_result_envelope.md",
        "bitrix_disk_upload_access_denied_per_folder_acl.md",
    ):
        (memory / name).write_text("# Обычная заметка\n", encoding="utf-8")

    matches = regulations.collect(_context(fake_home))["r8_r10_memory"][
        "bitrix_regulation"
    ]
    assert matches["exact"] == []
    assert [item["file"] for item in matches["candidates"]] == [
        "bitrix_box_bak_files_served_as_source.md",
        "bitrix_call_unwraps_result_envelope.md",
        "bitrix_disk_upload_access_denied_per_folder_acl.md",
    ]
    assert {item["why"] for item in matches["candidates"]} == {
        "имя начинается с bitrix_"
    }
    assert len(matches["candidates"]) <= 5
    assert matches["candidates_truncated"] is False


def test_r9_r10_same_rule(fake_home):
    memory = fake_home / ".codex" / "memories"
    memory.mkdir(parents=True)
    (memory / "notes.md").write_text(
        "---\nname: WORK_principles\n---\n# Принципы\n", encoding="utf-8"
    )
    (memory / "USER-PROFILE.MD").write_text("# Анкета\n", encoding="utf-8")

    cards = regulations.collect(_context(fake_home, profile="codex"))["r8_r10_memory"]
    assert [item["file"] for item in cards["principles"]["exact"]] == ["notes.md"]
    assert cards["principles"]["exact"][0]["name"] == "WORK_principles"
    assert [item["file"] for item in cards["user_profile"]["exact"]] == [
        "USER-PROFILE.MD"
    ]
    assert cards["user_profile"]["exact"][0]["name"] is None
    assert {
        item["memory_dir"]
        for group in (cards["principles"], cards["user_profile"])
        for item in group["exact"]
    } == {"$CODEX_HOME/memories"}


def test_r11_version_and_enabled(fake_home):
    _write_json(
        fake_home / ".claude" / "plugins" / "installed_plugins.json",
        {"plugins": {"superpowers@claude-plugins-official": [{"version": "6.1.0"}]}},
    )
    _write_json(
        fake_home / ".claude" / "settings.json",
        {"enabledPlugins": {"superpowers@claude-plugins-official": False}},
    )

    section = regulations.collect(_context(fake_home))
    assert section["r11_superpowers"] == {
        "installed": True,
        "version": "6.1.0",
        "version_at_least_6_2_0": False,
        "enabled": False,
    }
    assert section["r3_sources"]["installed_plugins"] == [
        "superpowers@claude-plugins-official"
    ]


def test_profile_codex_not_applicable(fake_home):
    ctx = _context(fake_home, profile="codex")
    section = regulations.collect(ctx)
    assert section["r1_exchange"] is None
    assert section["r3_sources"] is None
    assert section["r11_superpowers"] is None
    assert ctx.skipped == [
        {
            "section": "regulations",
            "reason": "not_applicable",
            "details": "profile=codex",
        }
    ]


def test_schema_valid(fake_home, run_collect):
    root = fake_home / "projects" / "schema"
    root.mkdir()
    result = run_collect("--root", root, "--only", "regulations")
    assert result.rc == 0
    validate(result.data)
