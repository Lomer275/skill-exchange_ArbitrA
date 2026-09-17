from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time

from envaudit.core import skills_index
from envaudit.core.context import Context, Flags
from envaudit.core.skills_index import memory_dir_name
from envaudit.sections import handoff, instructions, skills


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_skill(path: Path, name: str, body: str = "Body.\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"name: {name}\n"
        "description: English test skill\n"
        "---\n"
        + body,
        encoding="utf-8",
    )
    return path


def _mtime(path: Path, value: str) -> None:
    timestamp = datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()
    os.utime(path, (timestamp, timestamp))


def install_plugin(home: Path, names: list[str]) -> None:
    install_path = home / "plugin-cache" / "team-skills"
    for name in names:
        _write_skill(install_path / "skills" / name / "SKILL.md", name)
    _write_json(
        home / ".claude" / "plugins" / "installed_plugins.json",
        {
            "plugins": {
                "team-skills@skill-exchange": [
                    {"installPath": str(install_path), "version": "1.3.0", "scope": "user"}
                ]
            }
        },
    )
    settings = home / ".claude" / "settings.json"
    try:
        value = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    value.setdefault("enabledPlugins", {})["team-skills@skill-exchange"] = True
    _write_json(settings, value)


def memory_index(lines: int = 210, tail: int = 80) -> str:
    return "".join(
        f"- [card {number}](card-{number}.md) {'x' * tail}\n"
        for number in range(lines)
    )


def write_memory(home: Path, root: Path, *, index: str | None = None) -> Path:
    memory = home / ".claude" / "projects" / memory_dir_name(str(root)) / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    (memory / "card-0.md").write_text("card\n", encoding="utf-8")
    (memory / "MEMORY.md").write_text(index or memory_index(), encoding="utf-8")
    return memory


def irina_like(home: Path, *, with_memory: bool = True) -> Path:
    root = home / "projects" / "Битрикс"
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
    for name in ("HANDOFF_2026-09-05.md", "HANDOFF_2026-09-08.md"):
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
    install_plugin(home, ["close"])
    if with_memory:
        write_memory(home, root)
    return root


def write_user_skill(home: Path, name: str) -> Path:
    return _write_skill(home / ".claude" / "skills" / name / "SKILL.md", name)


def write_large_claude(root: Path, *, body: str | None = None) -> Path:
    text = body if body is not None else "Подробная инструкция.\n" * 100
    path = root / "CLAUDE.md"
    path.write_text("# Project\n\n## Большой раздел\n" + text, encoding="utf-8")
    return path


def add_linked_worktree(root: Path, worktree: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "seed"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "-qb", "test-worktree", str(worktree)],
        check=True,
    )
    return worktree


def collect_facts(home: Path, roots: list[Path], monkeypatch) -> dict:
    monkeypatch.setattr(skills_index, "MANAGED_DIRS", ())
    monkeypatch.setattr(skills, "MANAGED_DIRS", ())
    started = time.time()
    ctx = Context(Flags(), home, roots, started, started + 300)
    host = {"home": str(home), "codex_home": str(home / ".codex")}
    ctx.shared["host"] = host
    sections = {
        "instructions": instructions.collect(ctx),
        "handoff": handoff.collect(ctx),
        "skills": skills.collect(ctx),
        "secrets": {},
        "architecture": {},
    }
    return {
        "host": host,
        "roots": [{"path": str(root), "exists": True} for root in roots],
        "sections": sections,
    }


def write_facts(path: Path, facts: dict) -> Path:
    path.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
