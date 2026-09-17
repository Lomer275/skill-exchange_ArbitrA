from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat

from envaudit.reality import snapshot


def irina_like(root: Path, *, task_dir: bool = False, changelog: bool = True) -> Path:
    (root / ".git" / "info").mkdir(parents=True)
    (root / ".git" / "info" / "exclude").write_text("", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "handoffs").mkdir()
    (root / ".claude" / "skills" / "close").mkdir(parents=True)
    (root / ".claude" / "skills" / "accept").mkdir(parents=True)
    (root / "docs" / "CRM-HANDOFF.md").write_text("# Текущее состояние\n", encoding="utf-8")
    if changelog:
        (root / "docs" / "CRM-CHANGELOG.md").write_text("# Изменения\n", encoding="utf-8")
    for day in range(1, 8):
        (root / "handoffs" / f"HANDOFF_2026-09-{day:02d}.md").write_text(
            f"# Запись {day}\n", encoding="utf-8"
        )
    (root / "README.md").write_text("# Проект\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("# Правила проекта\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "### /close\nWrite `handoffs/HANDOFF_YYYY-MM-DD.md`.\n",
        encoding="utf-8",
    )
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / ".claude" / "skills" / "close" / "SKILL.md").write_text(
        "---\nname: close\ndescription: Close work\n---\n"
        "Write `handoffs/HANDOFF_YYYY-MM-DD.md`.\n",
        encoding="utf-8",
    )
    (root / ".claude" / "skills" / "accept" / "SKILL.md").write_text(
        "---\nname: accept\ndescription: Accept work\n---\n"
        "Update `docs/CRM-CHANGELOG.md`.\n",
        encoding="utf-8",
    )
    if task_dir:
        (root / "docs" / "3. CRM-tasks").mkdir()
    return root


def facts_document(
    home: Path,
    root: Path,
    *,
    profile: str = "claude",
    changelog: bool = True,
    changelog_writers: list[str] | None = None,
) -> dict:
    root = root.resolve()
    return {
        "host": {"profile": profile, "home": str(home)},
        "sections": {
            "handoff": {
                "roots": {
                    str(root): {
                        "canon": {"path": "docs/CRM-HANDOFF.md"},
                        "journals": [{"glob": "handoffs/HANDOFF_*.md"}],
                        "changelog": {
                            "canon": {"path": "docs/CRM-CHANGELOG.md"} if changelog else None,
                            "journals": [],
                        },
                        "close_writes": [],
                        "accept_writes": [],
                        "changelog_written_by": (
                            changelog_writers
                            if changelog_writers is not None
                            else (["accept"] if changelog else [])
                        ),
                    }
                }
            }
        },
    }


def write_facts(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def isolate_host(monkeypatch, home: Path, tmp_path: Path, *, tmp_pattern: str | None = None) -> None:
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    targets = (
        "~/.claude/projects/*/memory",
        "~/.claude/CLAUDE.md",
        "~/.claude/settings.json",
        "~/.claude/skills",
        "$CODEX_HOME/AGENTS.md",
        "$CODEX_HOME/memories",
        tmp_pattern or str(tmp_path / "claude-unused-*"),
        str(tmp_path / "sup-codex-unused"),
    )
    monkeypatch.setattr(snapshot, "OUTSIDE_TARGETS", targets)


def install_fake_tools(monkeypatch, tmp_path: Path) -> Path:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir(exist_ok=True)
    claude = binary_dir / "claude"
    claude.write_text(
        f"#!{os.sys.executable}\n"
        "import json\n"
        "import os\n"
        "from pathlib import Path\n"
        "mode = os.environ.get('FAKE_CLAUDE_MODE', 'works')\n"
        "cwd = Path.cwd()\n"
        "marker = os.environ.get('FAKE_CLAUDE_MARKER')\n"
        "if marker:\n"
        "    Path(marker).write_text('called', encoding='utf-8')\n"
        "if mode == 'works':\n"
        "    readme = cwd / 'README.md'\n"
        "    readme.write_text(readme.read_text(encoding='utf-8').replace('опечаткаа', 'опечатка'), encoding='utf-8')\n"
        "    handoff = cwd / os.environ.get('FAKE_HANDOFF', 'docs/CRM-HANDOFF.md')\n"
        "    handoff.parent.mkdir(parents=True, exist_ok=True)\n"
        "    with handoff.open('a', encoding='utf-8') as stream:\n"
        "        stream.write('\\nREADME: опечатка исправлена в T999.\\n')\n"
        "elif mode == 'journal':\n"
        "    target = cwd / 'handoffs/HANDOFF_2026-09-17.md'\n"
        "    target.parent.mkdir(parents=True, exist_ok=True)\n"
        "    target.write_text('README: опечатка исправлена\\n', encoding='utf-8')\n"
        "elif mode == 'leak':\n"
        "    target = Path.home() / '.claude' / 'CLAUDE.md'\n"
        "    target.parent.mkdir(parents=True, exist_ok=True)\n"
        "    target.write_text('outside change\\n', encoding='utf-8')\n"
        "subtype = 'success'\n"
        "is_error = False\n"
        "denials = []\n"
        "if mode == 'max_turns':\n"
        "    subtype = 'error_max_turns'\n"
        "    is_error = True\n"
        "elif mode == 'max_budget':\n"
        "    subtype = 'error_max_budget_usd'\n"
        "    is_error = True\n"
        "elif mode == 'denied':\n"
        "    denials = [{'tool': 'Write'}, {'tool': 'Skill'}]\n"
        "text = os.environ.get('FAKE_RESULT', 'Запрещено: сеть, коммиты и пуши.')\n"
        "print(json.dumps({'subtype': subtype, 'is_error': is_error, 'num_turns': 2, 'total_cost_usd': 0.01, 'usage': {'input_tokens': 10}, 'permission_denials': denials, 'result': text}, ensure_ascii=False))\n",
        encoding="utf-8",
    )
    crontab = binary_dir / "crontab"
    crontab.write_text(
        "#!/bin/sh\nprintf '%s\\n' '*/5 * * * * cd /home/x/p && python3 run.py'\n",
        encoding="utf-8",
    )
    systemctl = binary_dir / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    for path in (claude, crontab, systemctl):
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + os.environ.get("PATH", ""))
    return binary_dir


def write_run(path: Path, *, started_at: float, subtype: str = "success", denials: int = 0) -> Path:
    document = {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).timestamp(),
        "rc": 0,
        "timed_out": False,
        "parse_error": False,
        "subtype": subtype,
        "is_error": subtype != "success",
        "num_turns": 1,
        "total_cost_usd": 0.01,
        "permission_denials_count": denials,
        "result_text": "",
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path
