import json
from pathlib import Path

SKILLS_DIR = Path(__file__).parent.parent / "skills"


def scan_skills() -> list:
    if not SKILLS_DIR.exists():
        return []
    skills = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        meta_file = skill_dir / "meta.json"
        if not meta_file.exists():
            continue
        with open(meta_file, encoding="utf-8") as f:
            skills.append(json.load(f))
    return skills


def write_index(skills: list) -> None:
    index_file = SKILLS_DIR / "index.json"
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump({"skills": skills}, f, indent=2, ensure_ascii=False)


def generate_readme(skills: list) -> str:
    lines = [
        "# Skill Exchange ArbitrA",
        "",
        "Внутренняя библиотека Claude Code скиллов для команды.",
        "",
        "## Быстрый старт",
        "",
        "1. Клонируй репо: `git clone https://github.com/Lomer275/skill-exchange_ArbitrA.git`",
        "2. Установи pre-commit hook: `python cli/skill_exchange.py setup-hooks`",
        "3. Укажи путь к плагинам: `python cli/skill_exchange.py config --set-path <путь>`",
        "   - Windows: `C:\\Users\\<имя>\\.claude\\plugins`",
        "   - Mac/Linux: `~/.claude/plugins`",
        "4. Установи скилл: `python cli/skill_exchange.py install <name>`",
        "5. Перезапусти Claude Code",
        "",
        "## Каталог скиллов",
        "",
        "| Имя | Автор | Теги | Описание |",
        "|-----|-------|------|----------|",
    ]
    for s in skills:
        tags = ", ".join(s.get("tags", []))
        name = s["name"]
        author = s.get("author", "—")
        description = s.get("description", "")
        lines.append(f"| [{name}](skills/{name}/README.md) | {author} | {tags} | {description} |")

    lines += [
        "",
        "## Добавить свой скилл",
        "",
        "```bash",
        "python cli/skill_exchange.py new my-skill-name",
        "# Отредактируй skills/my-skill-name/{skill.md,meta.json,README.md}",
        "git add skills/my-skill-name",
        "git commit -m 'feat: add my-skill-name'",
        "git push",
        "```",
        "",
        "Подробнее: [CONTRIBUTING.md](CONTRIBUTING.md)",
        "",
        "> _Этот файл авто-генерируется pre-commit hook'ом. Не редактируй вручную._",
    ]
    return "\n".join(lines) + "\n"
