from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from envaudit.core.docs_layout import detect_prefix
from envaudit.handoff.canon import find_canon, normalize_target

from .arch_builders import make_repo
from .skill_builders import install_plugin


def _write_skill(path: Path, name: str, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"name: {name}\n"
        "description: English test skill\n"
        "---\n"
        f"{body}",
        encoding="utf-8",
    )
    return path


def _mtime(path: Path, value: str) -> None:
    timestamp = datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()
    os.utime(path, (timestamp, timestamp))


def irina_like(root: Path) -> Path:
    home = root.parent.parent
    (root / ".git" / "info").mkdir(parents=True)
    (root / ".git" / "info" / "exclude").write_text("", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "handoffs").mkdir()
    canon = root / "docs" / "CRM-HANDOFF.md"
    canon.write_text("# Текущее состояние\n", encoding="utf-8")
    changelog = root / "docs" / "CRM-CHANGELOG.md"
    changelog.write_text("# Изменения\n", encoding="utf-8")
    _mtime(canon, "2026-08-11T12:00:00")
    _mtime(changelog, "2026-08-10T12:00:00")
    for name in (
        "HANDOFF_2026-09-05.md",
        "HANDOFF_2026-09-08.md",
        "SCRUM_REPORT_2026-08-05.md",
    ):
        (root / "handoffs" / name).write_text("# Запись\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "# Rules\n"
        "### `/close` / `закрой день` / `заверши день`\n"
        "8. Write the daily Codex handoff to `handoffs/HANDOFF_YYYY-MM-DD_CODEX.md`.\n"
        "### `/intro`\n"
        "1. Read the newest handoff from `handoffs/HANDOFF_*.md`.\n",
        encoding="utf-8",
    )
    _write_skill(
        root / ".claude" / "skills" / "close" / "SKILL.md",
        "close",
        "Хендофф: запиши `handoffs/HANDOFF_{ДАТА}.md`\n"
        'Старые хендоффы: `find handoffs -name "HANDOFF_*.md"` — только предложи\n',
    )
    install_plugin(
        home,
        home / "plugin-cache" / "team-skills",
        "team-skills@skill-exchange",
        ["close"],
    )
    return root


def test_irina_canon_docs_journal_handoffs(fake_home):
    root = irina_like(fake_home / "projects" / "Битрикс")

    result = find_canon(root, detect_prefix(root), "HANDOFF")

    assert result["canon"] == {
        "path": "docs/CRM-HANDOFF.md",
        "rule": "docs",
        "date": "2026-08-11",
        "date_source": "mtime",
        "date_trust": "low",
        "dirty": None,
    }
    journal = result["journals"][0]
    assert journal["glob"] == "handoffs/HANDOFF_*.md"
    assert journal["declared_in"].startswith("AGENTS.md:")
    assert journal["files"] == 2
    assert journal["last"] == {
        "date": "2026-09-08",
        "source": "name",
        "trust": "high",
    }


def test_declared_single_file_wins(tmp_path):
    root = tmp_path / "declared"
    (root / "docs" / "state").mkdir(parents=True)
    (root / "CLAUDE.md").write_text(
        "состояние — в `docs/state/HANDOFF.md`\n", encoding="utf-8"
    )
    (root / "docs" / "state" / "HANDOFF.md").write_text("state\n", encoding="utf-8")
    (root / "SUP-HANDOFF.md").write_text("fallback\n", encoding="utf-8")

    result = find_canon(root, "SUP", "HANDOFF")

    assert result["canon"]["path"] == "docs/state/HANDOFF.md"
    assert result["canon"]["rule"] == "declared"


def test_declared_missing_falls_through(tmp_path):
    root = tmp_path / "missing"
    root.mkdir()
    (root / "CLAUDE.md").write_text("Use `docs/missing/HANDOFF.md`.\n", encoding="utf-8")
    (root / "SUP-HANDOFF.md").write_text("fallback\n", encoding="utf-8")

    result = find_canon(root, "SUP", "HANDOFF")

    assert result["canon"]["path"] == "SUP-HANDOFF.md"
    assert result["canon"]["rule"] == "root"


def test_root_over_docs(tmp_path):
    root = tmp_path / "both"
    (root / "docs").mkdir(parents=True)
    (root / "SUP-HANDOFF.md").write_text("root\n", encoding="utf-8")
    (root / "docs" / "SUP-HANDOFF.md").write_text("docs\n", encoding="utf-8")

    result = find_canon(root, "SUP", "HANDOFF")

    assert result["canon"]["path"] == "SUP-HANDOFF.md"
    assert result["canon"]["rule"] == "root"


def test_no_canon_candidates(tmp_path):
    root = tmp_path / "candidates"
    (root / "notes").mkdir(parents=True)
    (root / "x").mkdir()
    (root / "notes" / "handoff_old.md").write_text("old\n", encoding="utf-8")
    (root / "x" / "HANDOFF.md").write_text("other\n", encoding="utf-8")

    result = find_canon(root, None, "HANDOFF")

    assert result["canon"] is None
    assert [item["path"] for item in result["candidates"]] == [
        "notes/handoff_old.md",
        "x/HANDOFF.md",
    ]
    assert all(item["date"] is not None for item in result["candidates"])


def test_git_dates(tmp_path):
    committed = datetime.now(timezone.utc) - timedelta(days=3)
    root = make_repo(
        tmp_path / "repo",
        {},
        commits=[
            {
                "files": {"SUP-HANDOFF.md": "committed\n"},
                "date": committed.replace(microsecond=0).isoformat(),
            }
        ],
    )
    (root / "SUP-HANDOFF.md").write_text("changed\n", encoding="utf-8")

    result = find_canon(root, "SUP", "HANDOFF")

    assert result["canon"]["date"] == committed.date().isoformat()
    assert result["canon"]["date_source"] == "git"
    assert result["canon"]["date_trust"] == "high"
    assert result["canon"]["dirty"] is True


def test_normalize_target():
    assert normalize_target("HANDOFF_{ДАТА}.md") == "HANDOFF_*.md"
    assert normalize_target("HANDOFF_YYYY-MM-DD_CODEX.md") == "HANDOFF_*_CODEX.md"
    assert normalize_target("HANDOFF_<дата>.md") == "HANDOFF_*.md"
    assert normalize_target("HANDOFF_2026-09-08.md") == "HANDOFF_*.md"
