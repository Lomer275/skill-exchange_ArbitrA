from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import time

import pytest

from envaudit.core import skills_index
from envaudit.core.context import Context, Flags
from envaudit.sections import handoff

from .schema_check import validate
from .skill_builders import write_skill
from .test_handoff_canon import _mtime, _write_skill, irina_like
from .transcript_builders import iso, user_line, write_session


@pytest.fixture(autouse=True)
def _without_managed(monkeypatch):
    monkeypatch.setattr(skills_index, "MANAGED_DIRS", ())


def _collect(home: Path, root: Path) -> dict:
    started = time.time()
    ctx = Context(Flags(), home, [root], started, started + 300)
    return handoff.collect(ctx)["roots"][str(root.resolve())]


def test_irina_close_not_writing_canon(fake_home):
    root = irina_like(fake_home / "projects" / "Битрикс")
    write_session(
        fake_home,
        str(root),
        "close-calls",
        [user_line(iso(1), command="close", cwd=str(root)) for _ in range(5)],
    )

    result = _collect(fake_home, root)

    assert result["skills"]["close"]["resolves_to"]["source"] == "project"
    assert result["skills"]["close"]["also_listed_as"] == ["team-skills:close"]
    assert result["skills"]["close"]["invoked_window"] == {"close": 5}
    assert result["close_writes_canon"] is False
    assert result["codex_close_writes"][0]["writes_journal"] is True


def test_user_close_shadows_project(fake_home):
    root = fake_home / "projects" / "shadow"
    root.mkdir()
    write_skill(fake_home / ".claude" / "skills", "close")
    write_skill(root / ".claude" / "skills", "close")

    result = _collect(fake_home, root)

    assert result["skills"]["close"]["resolves_to"]["source"] == "user"


def test_changelog_written_by_accept(fake_home):
    root = fake_home / "projects" / "accept"
    root.mkdir()
    (root / "SUP-HANDOFF.md").write_text("state\n", encoding="utf-8")
    (root / "SUP-CHANGELOG.md").write_text("changes\n", encoding="utf-8")
    _write_skill(
        root / ".claude" / "skills" / "close" / "SKILL.md",
        "close",
        "update `SUP-HANDOFF.md`\n",
    )
    _write_skill(
        root / ".claude" / "skills" / "accept" / "SKILL.md",
        "accept",
        "обнови `SUP-CHANGELOG.md`\n",
    )

    result = _collect(fake_home, root)

    assert result["changelog_written_by"] == ["accept"]


def test_generic_target_matches_canon(fake_home):
    root = fake_home / "projects" / "generic"
    root.mkdir()
    (root / "SUP-HANDOFF.md").write_text("state\n", encoding="utf-8")
    (root / "SUP-CHANGELOG.md").write_text("changes\n", encoding="utf-8")
    _write_skill(
        root / ".claude" / "skills" / "close" / "SKILL.md",
        "close",
        "update `<PREFIX>-HANDOFF.md`\n",
    )
    _write_skill(
        root / ".claude" / "skills" / "accept" / "SKILL.md",
        "accept",
        "adds an entry to CHANGELOG.md\n",
    )

    result = _collect(fake_home, root)

    assert result["close_writes_canon"] is True
    assert result["close_writes"][0]["match"] == "generic"
    assert result["changelog_written_by"] == ["accept"]


def test_project_active_no_git(fake_home):
    root = fake_home / "projects" / "active"
    (root / "handoffs").mkdir(parents=True)
    canon = root / "SUP-HANDOFF.md"
    canon.write_text("state\n", encoding="utf-8")
    _mtime(canon, (datetime.now(timezone.utc) - timedelta(days=20)).isoformat())
    journal = root / "handoffs" / (
        "HANDOFF_" + (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat() + ".md"
    )
    journal.write_text("journal\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "Read `handoffs/HANDOFF_*.md`.\n", encoding="utf-8"
    )
    code = root / "app.py"
    code.write_text("VALUE = 1\n", encoding="utf-8")
    recent = datetime.now(timezone.utc) - timedelta(days=2)
    os.utime(code, (recent.timestamp(), recent.timestamp()))

    result = _collect(fake_home, root)

    assert result["project_active"]["value"] is True
    assert result["project_active"]["basis"] == "mtime"
    assert result["project_active"]["last_change_at"] == recent.date().isoformat()


def test_resolution_varies_by_cwd(fake_home):
    root = fake_home / "projects" / "varies"
    nested = root / "services" / "one"
    nested.mkdir(parents=True)
    write_skill(root / ".claude" / "skills", "close")
    write_skill(nested / ".claude" / "skills", "close")
    write_session(
        fake_home,
        str(nested),
        "nested",
        [user_line(iso(1), command="close", cwd=str(nested))],
    )

    result = _collect(fake_home, root)

    assert result["skills"]["close"]["resolution_varies_by_cwd"] is True


def test_schema_valid(fake_home, run_collect):
    root = irina_like(fake_home / "projects" / "Битрикс")
    empty = fake_home / "projects" / "empty"
    empty.mkdir()

    result = run_collect(
        "--root",
        root,
        "--root",
        empty,
        "--only",
        "handoff",
    )

    assert result.rc == 0, result.stdout
    validate(result.data)
