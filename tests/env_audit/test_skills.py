import time

import pytest

from envaudit.core import skills_index
from envaudit.core.context import Context, Flags
from envaudit.sections import skills

from .schema_check import validate
from .skill_builders import install_plugin, write_settings, write_skill
from .transcript_builders import (
    assistant_line,
    attachment_line,
    iso,
    tool_use,
    user_line,
    write_session,
)


@pytest.fixture(autouse=True)
def _without_managed(monkeypatch):
    monkeypatch.setattr(skills_index, "MANAGED_DIRS", ())
    monkeypatch.setattr(skills, "MANAGED_DIRS", ())


def _context(home, root):
    started = time.time()
    return Context(Flags(), home, [root], started, started + 300)


def _entries(section):
    return {item["qualified"]: item for item in section["entries"]}


def test_override_effective_plugin_false(fake_home, tmp_path):
    root = fake_home / "projects" / "project"
    root.mkdir()
    install_plugin(fake_home, tmp_path / "plugin", "team-skills@exchange", ["close"])
    write_skill(fake_home / ".claude" / "skills", "my-skill")
    write_settings(fake_home, {"skillOverrides": {"close": "off", "my-skill": "off"}})

    entries = _entries(skills.collect(_context(fake_home, root)))
    assert entries["team-skills:close"]["override_effective"] is False
    assert entries["my-skill"]["override_effective"] is True


def test_protected_reasons(fake_home, tmp_path):
    root = fake_home / "projects" / "project"
    root.mkdir()
    install_plugin(fake_home, tmp_path / "team", "team-skills@exchange", ["close"])
    install_plugin(
        fake_home,
        tmp_path / "superpowers",
        "superpowers@official",
        ["brainstorming"],
    )
    write_skill(fake_home / ".claude" / "skills", "env-audit")
    write_skill(fake_home / ".claude" / "skills", "my-skill")
    (root / "CLAUDE.md").write_text("Call /my-skill for this project.\n", encoding="utf-8")

    entries = _entries(skills.collect(_context(fake_home, root)))
    assert "mandatory" in entries["team-skills:close"]["protected_reasons"]
    assert "superpowers" in entries["superpowers:brainstorming"]["protected_reasons"]
    assert "env_audit" in entries["env-audit"]["protected_reasons"]
    assert "referenced" in entries["my-skill"]["protected_reasons"]


def test_mandatory_disabled_only_non_plugin(fake_home):
    root = fake_home / "projects" / "project"
    root.mkdir()
    write_skill(fake_home / ".claude" / "skills", "impl")
    write_skill(fake_home / ".claude" / "skills", "fix")
    write_settings(
        fake_home,
        {"skillOverrides": {"impl": "user-invocable-only", "fix": "name-only"}},
    )

    section = skills.collect(_context(fake_home, root))
    assert section["mandatory"]["disabled"] == ["impl"]


def test_invocations_window(fake_home, tmp_path):
    root = fake_home / "projects" / "project"
    root.mkdir()
    write_skill(fake_home / ".claude" / "skills", "close")
    install_plugin(fake_home, tmp_path / "plugin", "team-skills@exchange", ["impl"])
    write_session(
        fake_home,
        str(root),
        "usage",
        [
            user_line(iso(1), command="close", cwd=str(root)),
            assistant_line(
                iso(1),
                msg_id="m1",
                req_id="r1",
                cwd=str(root),
                tool_uses=[tool_use("Skill", id="one", skill="team-skills:impl")],
            ),
            user_line(iso(40), command="close", cwd=str(root)),
        ],
    )

    entries = _entries(skills.collect(_context(fake_home, root)))
    assert entries["close"]["invocations_window"] == 1
    assert entries["team-skills:impl"]["invocations_window"] == 1


def test_listing_actual_and_formula(fake_home):
    root = fake_home / "projects" / "project"
    root.mkdir()
    write_skill(fake_home / ".claude" / "skills", "my-skill")
    write_settings(fake_home, {"model": "opus[1m]"})
    write_session(
        fake_home,
        str(root),
        "listing",
        [
            user_line(iso(1), cwd=str(root)),
            attachment_line(
                iso(1),
                type="skill_listing",
                content="x" * 18_539,
                skill_count=58,
                cwd=str(root),
            ),
        ],
    )

    listing = skills.collect(_context(fake_home, root))["listing"]
    assert listing["actual"][0]["length"] == 18_539
    assert listing["actual"][0]["skill_count"] == 58
    assert listing["formula"]["model_window_tokens"] == 1_000_000
    assert listing["formula"]["budget_chars"] == 40_000


def test_shadowed_non_plugin(fake_home):
    root = fake_home / "projects" / "project"
    write_skill(fake_home / ".claude" / "skills", "close")
    write_skill(root / ".claude" / "skills", "close")

    item = skills.collect(_context(fake_home, root))["roots"][str(root)]
    assert item["shadowed_non_plugin"] == [
        {"name": "close", "sources": ["user", "project"]}
    ]


def test_broken_installed_plugins_keeps_local_sources(fake_home):
    root = fake_home / "projects" / "project"
    root.mkdir()
    write_skill(fake_home / ".claude" / "skills", "my-skill")
    path = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    ctx = _context(fake_home, root)

    section = skills.collect(ctx)
    assert "my-skill" in _entries(section)
    assert ctx.errors == [{"section": "skills", "kind": "installed_plugins_unreadable"}]


def test_schema_valid(fake_home, run_collect):
    root = fake_home / "projects" / "project"
    root.mkdir()
    write_skill(fake_home / ".claude" / "skills", "my-skill")
    result = run_collect("--root", root, "--only", "skills")
    assert result.rc == 0
    validate(result.data)
