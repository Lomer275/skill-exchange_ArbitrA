from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SKILLS_DIR = REPO_ROOT / "plugins" / "team-skills" / "skills"
INDEX_FILE = SKILLS_DIR / "index.json"

GITHUB_REPO = "Lomer275/skill-exchange_ArbitrA"
MARKETPLACE_NAME = "skill-exchange"
PLUGIN_NAME = "team-skills"

REQUIRED_META_FIELDS = ("name", "author", "description")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class InvalidSkillNameError(ValueError):
    pass


def validate_name(name: str) -> None:
    """Raise InvalidSkillNameError if name is unsafe or non-conforming.

    Skill names must be kebab-case ASCII, 1–64 chars. Rejects path-traversal
    attempts (`..`, slashes, absolute paths) by construction.
    """
    if not isinstance(name, str) or not SKILL_NAME_RE.match(name):
        raise InvalidSkillNameError(
            f"Невалидное имя скилла '{name}'. Разрешено: kebab-case из [a-z0-9-], "
            f"1–64 символов, начинается с буквы или цифры."
        )


def parse_frontmatter(text: str) -> dict | None:
    """Return parsed YAML frontmatter as dict, or None if missing/invalid.

    Minimal parser supporting `key: value` lines — no nested structures.
    Sufficient for SKILL.md frontmatter (name, description).
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    result = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            return None
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def validate_skill(skill_dir: Path) -> list[str]:
    """Return list of validation errors for a skill directory. Empty list = ok."""
    errors = []
    meta_file = skill_dir / "meta.json"
    skill_file = skill_dir / "SKILL.md"

    if not meta_file.exists():
        errors.append(f"{skill_dir.name}: отсутствует meta.json")
    else:
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{skill_dir.name}/meta.json: невалидный JSON ({e})")
            meta = None
        if meta is not None:
            for field in REQUIRED_META_FIELDS:
                if not meta.get(field):
                    errors.append(f"{skill_dir.name}/meta.json: отсутствует поле '{field}'")
            if meta.get("name") and meta["name"] != skill_dir.name:
                errors.append(
                    f"{skill_dir.name}/meta.json: поле 'name' ({meta['name']}) не совпадает с именем папки"
                )

    if not skill_file.exists():
        errors.append(f"{skill_dir.name}: отсутствует SKILL.md")
    else:
        text = skill_file.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if fm is None:
            errors.append(
                f"{skill_dir.name}/SKILL.md: отсутствует или невалиден YAML frontmatter (нужны поля name + description между --- ---)"
            )
        else:
            if not fm.get("name"):
                errors.append(f"{skill_dir.name}/SKILL.md: во frontmatter нет 'name'")
            elif fm["name"] != skill_dir.name:
                errors.append(
                    f"{skill_dir.name}/SKILL.md: frontmatter 'name' ({fm['name']}) не совпадает с именем папки"
                )
            if not fm.get("description"):
                errors.append(f"{skill_dir.name}/SKILL.md: во frontmatter нет 'description'")
    return errors


def validate_all() -> list[str]:
    """Validate every skill in SKILLS_DIR. Return aggregated errors."""
    if not SKILLS_DIR.exists():
        return []
    errors = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        errors.extend(validate_skill(skill_dir))
    return errors


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
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump({"skills": skills}, f, indent=2, ensure_ascii=False)


def generate_readme(skills: list) -> str:
    lines = [
        "# Skill Exchange ArbitrA",
        "",
        "Внутренняя библиотека Claude Code скиллов команды ArbitrA.",
        "Распространяется как Claude Code marketplace.",
        "",
        "## Установка (рекомендованный путь)",
        "",
        "В Claude Code:",
        "",
        "```",
        f"/plugin marketplace add {GITHUB_REPO}",
        f"/plugin install {PLUGIN_NAME}@{MARKETPLACE_NAME}",
        "```",
        "",
        f"После установки все скиллы доступны как `/{PLUGIN_NAME}:<имя-скилла>`.",
        "",
        "## Альтернатива: личная установка одного скилла через CLI",
        "",
        "```bash",
        f"git clone https://github.com/{GITHUB_REPO}.git",
        f"cd {GITHUB_REPO.split('/')[-1]}",
        "python cli/skill_exchange.py install <имя-скилла>",
        "```",
        "",
        "Копирует `SKILL.md` в `~/.claude/skills/<имя>/`. Скилл доступен как `/<имя>`.",
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
        lines.append(
            f"| [{name}](plugins/team-skills/skills/{name}/README.md) | {author} | {tags} | {description} |"
        )

    lines += [
        "",
        "## Добавить свой скилл",
        "",
        "```bash",
        "python cli/skill_exchange.py new my-skill-name",
        "# Отредактируй plugins/team-skills/skills/my-skill-name/{SKILL.md,meta.json,README.md}",
        "git add plugins/team-skills/skills/my-skill-name",
        "git commit -m 'feat: add my-skill-name'",
        "git push",
        "```",
        "",
        "Подробнее: [CONTRIBUTING.md](CONTRIBUTING.md)",
        "",
        "> _Этот файл авто-генерируется pre-commit hook'ом. Не редактируй вручную._",
    ]
    return "\n".join(lines) + "\n"
