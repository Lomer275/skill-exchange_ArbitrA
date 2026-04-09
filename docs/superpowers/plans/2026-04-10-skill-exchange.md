# Skill Exchange ArbitrA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Создать git-репозиторий с CLI-инструментом для обмена Claude Code скиллами внутри команды из 4–6 человек.

**Architecture:** Python CLI (`skill_exchange.py`) с двумя вспомогательными модулями (`config.py`, `indexer.py`). Pre-commit hook автоматически регенерирует каталог (`skills/index.json`, `README.md`) при каждом коммите. Скиллы хранятся как папки с тремя файлами: `skill.md`, `meta.json`, `README.md`.

**Tech Stack:** Python 3.8+, argparse (stdlib), pytest (тесты), bash + PowerShell (скрипты установки).

---

## File Map

| Файл | Ответственность |
|---|---|
| `cli/config.py` | Чтение/запись `~/.skill-exchange/config.json` |
| `cli/indexer.py` | Сканирование `skills/`, генерация `index.json` и `README.md` |
| `cli/skill_exchange.py` | argparse entry point, команды CLI |
| `hooks/pre-commit` | Git hook: вызывает indexer, git-add результатов |
| `scripts/install.sh` | Ручная установка одного скилла (bash, без Python) |
| `scripts/install.ps1` | То же для Windows PowerShell |
| `skills/index.json` | Авто-генерируемый каталог (не редактировать вручную) |
| `skills/example-skill/*` | Пример скилла с заполненными шаблонами |
| `README.md` | Авто-генерируемый главный каталог |
| `CONTRIBUTING.md` | Гайд для команды (редактируется вручную) |
| `tests/conftest.py` | Добавляет `cli/` в sys.path для тестов |
| `tests/test_config.py` | Тесты модуля config |
| `tests/test_indexer.py` | Тесты модуля indexer |
| `tests/test_cli.py` | Интеграционные тесты CLI команд |

---

## Task 1: Project skeleton

**Files:**
- Create: `requirements-dev.txt`
- Create: `pytest.ini`
- Create: `.gitignore`
- Create: `tests/conftest.py`
- Create: `cli/__init__.py` (пусто)
- Create: `tests/__init__.py` (пусто)

- [ ] **Step 1: Создать `requirements-dev.txt`**

```
pytest>=7.0
```

- [ ] **Step 2: Создать `pytest.ini`**

```ini
[pytest]
testpaths = tests
```

- [ ] **Step 3: Создать `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
dist/
.skill-exchange/
```

- [ ] **Step 4: Создать `tests/conftest.py`**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "cli"))
```

- [ ] **Step 5: Создать пустые `__init__.py`**

Создать пустой файл `cli/__init__.py`.
Создать пустой файл `tests/__init__.py`.

- [ ] **Step 6: Убедиться что pytest запускается**

```bash
cd c:/Users/Zhigalov/Desktop/skill-exchange_ArbitrA
pip install -r requirements-dev.txt
pytest
```

Ожидаемый вывод: `no tests ran` или `0 passed`.

- [ ] **Step 7: Commit**

```bash
git add requirements-dev.txt pytest.ini .gitignore tests/conftest.py cli/__init__.py tests/__init__.py
git commit -m "chore: project skeleton, pytest setup"
```

---

## Task 2: `config.py` — управление локальным конфигом

**Files:**
- Create: `cli/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_config.py`:

```python
import json
import pytest
from pathlib import Path
from unittest.mock import patch


def patched_config(tmp_path):
    """Context manager: подменяет CONFIG_DIR и CONFIG_FILE на tmp_path."""
    import config as cfg
    return patch.multiple(
        cfg,
        CONFIG_DIR=tmp_path,
        CONFIG_FILE=tmp_path / "config.json",
    )


def test_load_config_returns_default_when_no_file(tmp_path):
    with patched_config(tmp_path):
        import config as cfg
        result = cfg.load_config()
        assert result["installed"] == []
        assert "default_path" in result


def test_save_and_load_roundtrip(tmp_path):
    with patched_config(tmp_path):
        import config as cfg
        data = {"default_path": "/custom/path", "installed": ["skill-a"]}
        cfg.save_config(data)
        loaded = cfg.load_config()
        assert loaded == data


def test_save_creates_directory(tmp_path):
    nested = tmp_path / "deep" / "dir"
    with patch.multiple("config", CONFIG_DIR=nested, CONFIG_FILE=nested / "config.json"):
        import config as cfg
        cfg.save_config({"default_path": "/x", "installed": []})
        assert (nested / "config.json").exists()
```

- [ ] **Step 2: Запустить тест — убедиться что падает**

```bash
pytest tests/test_config.py -v
```

Ожидаемый вывод: `ERROR` или `ModuleNotFoundError: No module named 'config'`.

- [ ] **Step 3: Написать `cli/config.py`**

```python
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".skill-exchange"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "default_path": str(Path.home() / ".claude" / "plugins"),
    "installed": [],
}


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
```

- [ ] **Step 4: Запустить тест — убедиться что проходит**

```bash
pytest tests/test_config.py -v
```

Ожидаемый вывод: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add cli/config.py tests/test_config.py
git commit -m "feat: config module with load/save"
```

---

## Task 3: `indexer.py` — сканирование скиллов и генерация каталога

**Files:**
- Create: `cli/indexer.py`
- Create: `tests/test_indexer.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_indexer.py`:

```python
import json
import pytest
from pathlib import Path
from unittest.mock import patch


def make_skill(skills_dir: Path, name: str, author: str = "test", tags=None, description: str = "desc") -> dict:
    """Создаёт папку скилла в tmp skills_dir, возвращает meta dict."""
    skill_dir = skills_dir / name
    skill_dir.mkdir()
    meta = {
        "name": name,
        "display_name": name.replace("-", " ").title(),
        "author": author,
        "version": "1.0.0",
        "description": description,
        "tags": tags or [],
        "created": "2026-04-10",
    }
    (skill_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (skill_dir / "skill.md").write_text(f"# {name}", encoding="utf-8")
    (skill_dir / "README.md").write_text(f"# {name} readme", encoding="utf-8")
    return meta


def patched_skills_dir(tmp_path):
    import indexer
    return patch.object(indexer, "SKILLS_DIR", tmp_path)


def test_scan_finds_skills_alphabetically(tmp_path):
    with patched_skills_dir(tmp_path):
        make_skill(tmp_path, "beta-skill")
        make_skill(tmp_path, "alpha-skill")
        import indexer
        result = indexer.scan_skills()
        assert len(result) == 2
        assert result[0]["name"] == "alpha-skill"
        assert result[1]["name"] == "beta-skill"


def test_scan_ignores_non_directories(tmp_path):
    with patched_skills_dir(tmp_path):
        make_skill(tmp_path, "skill-a")
        (tmp_path / "index.json").write_text("{}")  # файл, не папка
        import indexer
        result = indexer.scan_skills()
        assert len(result) == 1


def test_scan_ignores_dirs_without_meta(tmp_path):
    with patched_skills_dir(tmp_path):
        make_skill(tmp_path, "valid-skill")
        (tmp_path / "no-meta-dir").mkdir()  # папка без meta.json
        import indexer
        result = indexer.scan_skills()
        assert len(result) == 1


def test_write_index_creates_file(tmp_path):
    with patched_skills_dir(tmp_path):
        import indexer
        skills = [{"name": "s1", "description": "d1", "tags": []}]
        indexer.write_index(skills)
        data = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
        assert data["skills"] == skills


def test_generate_readme_contains_skill_names(tmp_path):
    import indexer
    skills = [
        {"name": "skill-a", "author": "ivan", "tags": ["git"], "description": "does git"},
        {"name": "skill-b", "author": "anna", "tags": [], "description": "does b"},
    ]
    readme = indexer.generate_readme(skills)
    assert "skill-a" in readme
    assert "skill-b" in readme
    assert "ivan" in readme
    assert "does git" in readme
```

- [ ] **Step 2: Запустить тесты — убедиться что падают**

```bash
pytest tests/test_indexer.py -v
```

Ожидаемый вывод: `ERROR` или `ModuleNotFoundError: No module named 'indexer'`.

- [ ] **Step 3: Написать `cli/indexer.py`**

```python
import json
from pathlib import Path

SKILLS_DIR = Path(__file__).parent.parent / "skills"


def scan_skills() -> list:
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
        "1. Клонируй репо: `git clone <url>`",
        "2. Настрой путь установки: `python cli/skill_exchange.py config --set-path /твой/путь/к/plugins`",
        "3. Установи скилл: `python cli/skill_exchange.py install <name>`",
        "4. Перезапусти Claude Code",
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
```

- [ ] **Step 4: Запустить тесты — убедиться что проходят**

```bash
pytest tests/test_indexer.py -v
```

Ожидаемый вывод: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add cli/indexer.py tests/test_indexer.py
git commit -m "feat: indexer module — scan skills, generate index.json and README"
```

---

## Task 4: CLI — `list` команда

**Files:**
- Create: `cli/skill_exchange.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_cli.py`:

```python
import json
import pytest
from pathlib import Path
from unittest.mock import patch


def run_cli(args: list, skills_dir: Path = None):
    """Вызывает main() с подменёнными аргументами и возвращает stdout."""
    import sys
    from io import StringIO
    import skill_exchange

    captured = StringIO()
    with patch("sys.argv", ["skill-exchange"] + args):
        with patch("sys.stdout", captured):
            if skills_dir:
                with patch("indexer.SKILLS_DIR", skills_dir):
                    skill_exchange.main()
            else:
                skill_exchange.main()
    return captured.getvalue()


def make_index(skills_dir: Path, skills: list):
    skills_dir.mkdir(parents=True, exist_ok=True)
    index = {"skills": skills}
    (skills_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")


def test_list_shows_all_skills(tmp_path):
    skills = [
        {"name": "skill-a", "author": "ivan", "tags": ["git"], "description": "does git"},
        {"name": "skill-b", "author": "anna", "tags": [], "description": "does b"},
    ]
    make_index(tmp_path, skills)
    output = run_cli(["list"], skills_dir=tmp_path)
    assert "skill-a" in output
    assert "skill-b" in output
    assert "ivan" in output


def test_list_filters_by_tag(tmp_path):
    skills = [
        {"name": "skill-a", "author": "ivan", "tags": ["git"], "description": "desc"},
        {"name": "skill-b", "author": "anna", "tags": ["python"], "description": "desc"},
    ]
    make_index(tmp_path, skills)
    output = run_cli(["list", "--tag", "git"], skills_dir=tmp_path)
    assert "skill-a" in output
    assert "skill-b" not in output


def test_list_empty_catalog(tmp_path):
    make_index(tmp_path, [])
    output = run_cli(["list"], skills_dir=tmp_path)
    assert "не найдены" in output or output.strip() == "" or "пуст" in output
```

- [ ] **Step 2: Запустить — убедиться что падает**

```bash
pytest tests/test_cli.py -v
```

Ожидаемый вывод: `ERROR` или `ModuleNotFoundError: No module named 'skill_exchange'`.

- [ ] **Step 3: Написать `cli/skill_exchange.py` с `list` командой**

```python
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg_module
import indexer as idx_module

REPO_ROOT = Path(__file__).parent.parent
SKILLS_DIR = REPO_ROOT / "skills"


# ── list ──────────────────────────────────────────────────────────────────────

def cmd_list(args):
    index_file = idx_module.SKILLS_DIR / "index.json"
    if not index_file.exists():
        print("Каталог пуст. Запусти git pull для обновления.")
        return
    with open(index_file, encoding="utf-8") as f:
        data = json.load(f)
    skills = data.get("skills", [])
    if args.tag:
        skills = [s for s in skills if args.tag in s.get("tags", [])]
    if not skills:
        print("Скиллы не найдены.")
        return
    for s in skills:
        tags = ", ".join(s.get("tags", []))
        print(f"  {s['name']:<28} {s.get('author', '—'):<12} [{tags}]  {s.get('description', '')}")


# ── install ────────────────────────────────────────────────────────────────────

def cmd_install(args):
    config = cfg_module.load_config()
    skill_src = idx_module.SKILLS_DIR / args.name
    if not skill_src.exists():
        print(f"Скилл '{args.name}' не найден в репо.")
        sys.exit(1)

    if args.desktop:
        readme = skill_src / "README.md"
        text = readme.read_text(encoding="utf-8") if readme.exists() else str(skill_src / "skill.md")
        try:
            if sys.platform == "win32":
                subprocess.run("clip", input=text.encode("utf-16"), check=True)
            elif sys.platform == "darwin":
                subprocess.run(["pbcopy"], input=text.encode(), check=True)
            else:
                subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
            print(f"README скилла '{args.name}' скопирован в буфер обмена.")
            print("Вставь его в системный промпт Claude Desktop Project.")
        except Exception as e:
            print(f"Не удалось скопировать в буфер: {e}")
            print(text)
        return

    if args.path:
        target_dir = Path(args.path)
    elif args.global_:
        target_dir = Path.home() / ".claude" / "plugins"
    elif args.project:
        target_dir = Path.cwd() / ".claude" / "plugins"
    else:
        target_dir = Path(config["default_path"])

    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / args.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(skill_src, dest)
    print(f"Скилл '{args.name}' установлен в {dest}")

    if args.name not in config["installed"]:
        config["installed"].append(args.name)
        cfg_module.save_config(config)


# ── config ─────────────────────────────────────────────────────────────────────

def cmd_config(args):
    config = cfg_module.load_config()
    if args.set_path:
        config["default_path"] = args.set_path
        cfg_module.save_config(config)
        print(f"Дефолтный путь установки сохранён: {args.set_path}")
    else:
        print(json.dumps(config, indent=2, ensure_ascii=False))


# ── new ────────────────────────────────────────────────────────────────────────

def cmd_new(args):
    skill_dir = idx_module.SKILLS_DIR / args.name
    if skill_dir.exists():
        print(f"Скилл '{args.name}' уже существует.")
        sys.exit(1)
    skill_dir.mkdir(parents=True)

    today = date.today().isoformat()
    author = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    display_name = args.name.replace("-", " ").title()
    meta = {
        "name": args.name,
        "display_name": display_name,
        "author": author,
        "version": "1.0.0",
        "description": "Описание скилла",
        "tags": [],
        "created": today,
    }
    (skill_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (skill_dir / "skill.md").write_text(
        f"# {display_name}\n\n<!-- Опиши что делает скилл. Это содержимое загружается в Claude Code. -->\n",
        encoding="utf-8",
    )
    (skill_dir / "README.md").write_text(
        f"# {display_name}\n\n"
        f"## Что делает\n\n<!-- Опиши скилл -->\n\n"
        f"## Установка\n\n"
        f"```bash\npython cli/skill_exchange.py install {args.name}\n```\n\n"
        f"Или вручную: скопировать папку `skills/{args.name}` в директорию плагинов Claude Code.\n\n"
        f"## Использование\n\n<!-- Опиши как использовать -->\n\n"
        f"## Автор\n\n{author}\n",
        encoding="utf-8",
    )
    print(f"Скилл '{args.name}' создан в {skill_dir}")
    print(f"Отредактируй: skills/{args.name}/skill.md, meta.json, README.md")
    print(f"Затем: git add skills/{args.name} && git commit && git push")


# ── update ─────────────────────────────────────────────────────────────────────

def cmd_update(args):
    print("Обновляем репо...")
    subprocess.run(["git", "pull"], cwd=REPO_ROOT, check=True)
    config = cfg_module.load_config()
    for name in list(config.get("installed", [])):
        print(f"Переустанавливаем {name}...")
        skill_src = idx_module.SKILLS_DIR / name
        if not skill_src.exists():
            print(f"  Скилл '{name}' не найден в репо, пропускаем.")
            continue
        target_dir = Path(config["default_path"])
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(skill_src, dest)
        print(f"  Установлен в {dest}")
    print("Готово.")


# ── setup-hooks ────────────────────────────────────────────────────────────────

def cmd_setup_hooks(args):
    hook_src = REPO_ROOT / "hooks" / "pre-commit"
    hook_dst = REPO_ROOT / ".git" / "hooks" / "pre-commit"
    if not hook_src.exists():
        print(f"Hook файл не найден: {hook_src}")
        sys.exit(1)
    shutil.copy(hook_src, hook_dst)
    hook_dst.chmod(0o755)
    print(f"Pre-commit hook установлен: {hook_dst}")
    print("Теперь при каждом коммите каталог скиллов будет обновляться автоматически.")


# ── argparse ───────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill-exchange",
        description="Менеджер Claude Code скиллов команды",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="Показать все скиллы")
    p_list.add_argument("--tag", help="Фильтр по тегу")

    p_install = sub.add_parser("install", help="Установить скилл")
    p_install.add_argument("name", help="Имя скилла")
    p_install.add_argument("--global", dest="global_", action="store_true",
                           help="Установить в ~/.claude/plugins/")
    p_install.add_argument("--project", action="store_true",
                           help="Установить в ./.claude/plugins/")
    p_install.add_argument("--path", help="Установить в произвольный путь")
    p_install.add_argument("--desktop", action="store_true",
                           help="Скопировать README в буфер (Claude Desktop)")

    p_cfg = sub.add_parser("config", help="Настройки CLI")
    p_cfg.add_argument("--set-path", metavar="PATH", help="Сохранить дефолтный путь установки")

    p_new = sub.add_parser("new", help="Создать новый скилл с шаблонами")
    p_new.add_argument("name", help="Имя нового скилла (kebab-case)")

    sub.add_parser("update", help="git pull + переустановить все установленные скиллы")
    sub.add_parser("setup-hooks", help="Установить git pre-commit hook")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    {
        "list": cmd_list,
        "install": cmd_install,
        "config": cmd_config,
        "new": cmd_new,
        "update": cmd_update,
        "setup-hooks": cmd_setup_hooks,
    }[args.command](args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Запустить тесты list — убедиться что проходят**

```bash
pytest tests/test_cli.py -v
```

Ожидаемый вывод: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add cli/skill_exchange.py tests/test_cli.py
git commit -m "feat: CLI scaffold with list command"
```

---

## Task 5: CLI — `install` команда (тесты)

**Files:**
- Modify: `tests/test_cli.py` (добавить тесты install)

- [ ] **Step 1: Добавить тесты install в конец `tests/test_cli.py`**

```python
import shutil


def make_skill_in_dir(skills_dir: Path, name: str):
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": name, "display_name": name.title(),
        "author": "test", "version": "1.0.0",
        "description": "test skill", "tags": [], "created": "2026-04-10",
    }
    (skill_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (skill_dir / "skill.md").write_text("# skill", encoding="utf-8")
    (skill_dir / "README.md").write_text("# readme", encoding="utf-8")


def test_install_copies_skill_to_target(tmp_path):
    skills_dir = tmp_path / "skills"
    install_dir = tmp_path / "plugins"
    make_skill_in_dir(skills_dir, "cool-skill")
    config = {"default_path": str(install_dir), "installed": []}
    with patch("indexer.SKILLS_DIR", skills_dir), \
         patch("config.load_config", return_value=config), \
         patch("config.save_config"):
        import skill_exchange
        with patch("sys.argv", ["skill-exchange", "install", "cool-skill"]):
            skill_exchange.main()
    assert (install_dir / "cool-skill" / "skill.md").exists()


def test_install_missing_skill_exits(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    config = {"default_path": str(tmp_path / "plugins"), "installed": []}
    with patch("indexer.SKILLS_DIR", skills_dir), \
         patch("config.load_config", return_value=config), \
         patch("config.save_config"):
        import skill_exchange
        with patch("sys.argv", ["skill-exchange", "install", "nonexistent"]):
            with pytest.raises(SystemExit):
                skill_exchange.main()


def test_install_path_flag(tmp_path):
    skills_dir = tmp_path / "skills"
    custom_dir = tmp_path / "custom"
    make_skill_in_dir(skills_dir, "my-skill")
    config = {"default_path": str(tmp_path / "plugins"), "installed": []}
    with patch("indexer.SKILLS_DIR", skills_dir), \
         patch("config.load_config", return_value=config), \
         patch("config.save_config"):
        import skill_exchange
        with patch("sys.argv", ["skill-exchange", "install", "my-skill", "--path", str(custom_dir)]):
            skill_exchange.main()
    assert (custom_dir / "my-skill").exists()
```

- [ ] **Step 2: Запустить тесты — убедиться что проходят**

```bash
pytest tests/test_cli.py -v
```

Ожидаемый вывод: `6 passed`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cli.py
git commit -m "test: install command coverage"
```

---

## Task 6: CLI — `new` команда (тесты)

**Files:**
- Modify: `tests/test_cli.py` (добавить тесты new)

- [ ] **Step 1: Добавить тесты new в конец `tests/test_cli.py`**

```python
def test_new_creates_skill_files(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    with patch("indexer.SKILLS_DIR", skills_dir):
        import skill_exchange
        with patch("sys.argv", ["skill-exchange", "new", "test-skill"]):
            skill_exchange.main()
    skill_dir = skills_dir / "test-skill"
    assert (skill_dir / "skill.md").exists()
    assert (skill_dir / "meta.json").exists()
    assert (skill_dir / "README.md").exists()
    import json as _json
    meta = _json.loads((skill_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["name"] == "test-skill"
    assert meta["version"] == "1.0.0"


def test_new_exits_if_skill_exists(tmp_path):
    skills_dir = tmp_path / "skills"
    (skills_dir / "existing-skill").mkdir(parents=True)
    with patch("indexer.SKILLS_DIR", skills_dir):
        import skill_exchange
        with patch("sys.argv", ["skill-exchange", "new", "existing-skill"]):
            with pytest.raises(SystemExit):
                skill_exchange.main()
```

- [ ] **Step 2: Запустить — убедиться что проходят**

```bash
pytest tests/test_cli.py -v
```

Ожидаемый вывод: `8 passed`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cli.py
git commit -m "test: new command coverage"
```

---

## Task 7: Pre-commit hook

**Files:**
- Create: `hooks/pre-commit`

- [ ] **Step 1: Создать `hooks/pre-commit`**

```python
#!/usr/bin/env python3
"""
Pre-commit hook: перегенерирует skills/index.json и README.md.
Устанавливается через: python cli/skill_exchange.py setup-hooks
"""
import subprocess
import sys
from pathlib import Path

# Найти корень репо через git
result = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True, check=True,
)
repo_root = Path(result.stdout.strip())
sys.path.insert(0, str(repo_root / "cli"))

import indexer

skills = indexer.scan_skills()
indexer.write_index(skills)

readme_content = indexer.generate_readme(skills)
(repo_root / "README.md").write_text(readme_content, encoding="utf-8")

subprocess.run(
    ["git", "add", "skills/index.json", "README.md"],
    cwd=repo_root,
    check=True,
)
print(f"[pre-commit] Каталог обновлён: {len(skills)} скилл(ов)")
```

- [ ] **Step 2: Сделать файл исполняемым (на Mac/Linux)**

На Windows этот шаг пропустить. На Mac/Linux:
```bash
chmod +x hooks/pre-commit
```

- [ ] **Step 3: Установить hook и убедиться что он работает**

```bash
python cli/skill_exchange.py setup-hooks
```

Ожидаемый вывод: `Pre-commit hook установлен: .git/hooks/pre-commit`

- [ ] **Step 4: Commit**

```bash
git add hooks/pre-commit
git commit -m "feat: pre-commit hook auto-regenerates index.json and README"
```

---

## Task 8: Скрипты ручной установки

**Files:**
- Create: `scripts/install.sh`
- Create: `scripts/install.ps1`

- [ ] **Step 1: Создать `scripts/install.sh`**

```bash
#!/usr/bin/env bash
# Ручная установка одного скилла без CLI.
# Использование: bash scripts/install.sh <skill-name> [target-dir]
#
# Примеры:
#   bash scripts/install.sh git-commit-helper
#   bash scripts/install.sh git-commit-helper ~/.claude/plugins

set -euo pipefail

SKILL_NAME="${1:?Укажи имя скилла: bash install.sh <skill-name> [target-dir]}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/skills"
SKILL_SRC="$SKILLS_DIR/$SKILL_NAME"

if [ ! -d "$SKILL_SRC" ]; then
    echo "Ошибка: скилл '$SKILL_NAME' не найден в $SKILLS_DIR"
    echo "Доступные скиллы:"
    ls "$SKILLS_DIR" | grep -v index.json
    exit 1
fi

TARGET_DIR="${2:-$HOME/.claude/plugins}"
mkdir -p "$TARGET_DIR"

cp -r "$SKILL_SRC" "$TARGET_DIR/"
echo "Скилл '$SKILL_NAME' установлен в $TARGET_DIR/$SKILL_NAME"
echo "Перезапусти Claude Code для применения."
```

- [ ] **Step 2: Создать `scripts/install.ps1`**

```powershell
# Ручная установка одного скилла без CLI.
# Использование: .\scripts\install.ps1 <skill-name> [target-dir]
#
# Примеры:
#   .\scripts\install.ps1 git-commit-helper
#   .\scripts\install.ps1 git-commit-helper C:\Users\me\.claude\plugins

param(
    [Parameter(Mandatory=$true)]
    [string]$SkillName,

    [string]$TargetDir = "$env:USERPROFILE\.claude\plugins"
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
$SkillsDir = Join-Path $RepoRoot "skills"
$SkillSrc  = Join-Path $SkillsDir $SkillName

if (-not (Test-Path $SkillSrc)) {
    Write-Error "Скилл '$SkillName' не найден в $SkillsDir"
    Write-Host "Доступные скиллы:"
    Get-ChildItem $SkillsDir -Directory | Select-Object -ExpandProperty Name
    exit 1
}

New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
$Dest = Join-Path $TargetDir $SkillName
if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
Copy-Item -Recurse $SkillSrc $Dest

Write-Host "Скилл '$SkillName' установлен в $Dest"
Write-Host "Перезапусти Claude Code для применения."
```

- [ ] **Step 3: Commit**

```bash
git add scripts/install.sh scripts/install.ps1
git commit -m "feat: manual install scripts for bash and powershell"
```

---

## Task 9: Пример скилла

**Files:**
- Create: `skills/example-skill/skill.md`
- Create: `skills/example-skill/meta.json`
- Create: `skills/example-skill/README.md`

- [ ] **Step 1: Создать `skills/example-skill/meta.json`**

```json
{
  "name": "example-skill",
  "display_name": "Example Skill",
  "author": "team",
  "version": "1.0.0",
  "description": "Демонстрационный скилл — шаблон для создания своих",
  "tags": ["example", "template"],
  "created": "2026-04-10"
}
```

- [ ] **Step 2: Создать `skills/example-skill/skill.md`**

```markdown
# Example Skill

Это демонстрационный скилл. Он показывает структуру и формат скилла для Claude Code.

## Что умеет этот скилл

Когда этот скилл активирован, Claude будет:
- Демонстрировать пример структуры скилла
- Отвечать на вопросы "как создать скилл?"

## Пример инструкции для Claude

Ты помогаешь пользователю создавать качественные Claude Code скиллы.
При просьбе создать скилл — уточни его назначение, затем создай структуру
с skill.md, meta.json и README.md по стандарту команды.
```

- [ ] **Step 3: Создать `skills/example-skill/README.md`**

```markdown
# Example Skill

Демонстрационный скилл — шаблон для создания своих.

## Что делает

Показывает правильную структуру скилла. Используй как отправную точку при создании нового скилла.

## Установка

```bash
python cli/skill_exchange.py install example-skill
```

Или вручную: скопировать папку `skills/example-skill` в директорию плагинов Claude Code.

## Использование

После установки скилл доступен в Claude Code. Используй его как шаблон:
скопируй папку `skills/example-skill`, переименуй, отредактируй три файла.

## Автор

team
```

- [ ] **Step 4: Commit с auto-обновлением каталога**

```bash
git add skills/example-skill
git commit -m "feat: add example-skill as template"
```

Pre-commit hook автоматически обновит `skills/index.json` и `README.md`.
Убедись что в выводе коммита видно: `[pre-commit] Каталог обновлён: 1 скилл(ов)`.

---

## Task 10: Документация

**Files:**
- Create: `CONTRIBUTING.md`

> `README.md` авто-генерируется hook'ом — не создавать вручную.

- [ ] **Step 1: Создать `CONTRIBUTING.md`**

```markdown
# Contributing to Skill Exchange ArbitrA

Гайд для команды по добавлению и обновлению Claude Code скиллов.

## Требования

- Python 3.8+
- Git
- Клонированный репозиторий

## Первичная настройка (один раз)

```bash
# 1. Клонируй репо
git clone <url> skill-exchange_ArbitrA
cd skill-exchange_ArbitrA

# 2. Установи pre-commit hook (обновляет каталог при каждом коммите)
python cli/skill_exchange.py setup-hooks

# 3. Укажи куда устанавливать скиллы локально
python cli/skill_exchange.py config --set-path /путь/к/твоим/плагинам
# Например:
#   Windows: python cli/skill_exchange.py config --set-path C:\Users\me\.claude\plugins
#   Mac/Linux: python cli/skill_exchange.py config --set-path ~/.claude/plugins
```

## Установить скилл из библиотеки

```bash
# Посмотреть все скиллы
python cli/skill_exchange.py list

# Установить конкретный скилл
python cli/skill_exchange.py install <skill-name>

# Установить в конкретную папку
python cli/skill_exchange.py install <skill-name> --path /custom/path

# Для Claude Desktop: скопировать README в буфер обмена
python cli/skill_exchange.py install <skill-name> --desktop
```

После установки перезапусти Claude Code.

## Добавить новый скилл

```bash
# 1. Создать папку скилла с шаблонами
python cli/skill_exchange.py new my-skill-name

# 2. Отредактируй три файла:
#    skills/my-skill-name/skill.md    — содержимое скилла для Claude
#    skills/my-skill-name/meta.json   — метаданные (имя, теги, описание)
#    skills/my-skill-name/README.md   — документация для команды

# 3. Запушь — каталог обновится автоматически
git add skills/my-skill-name
git commit -m "feat: add my-skill-name"
git push
```

## Формат `meta.json`

```json
{
  "name": "kebab-case-name",
  "display_name": "Human Readable Name",
  "author": "твоё имя",
  "version": "1.0.0",
  "description": "Одна строка: что делает скилл",
  "tags": ["tag1", "tag2"],
  "created": "YYYY-MM-DD"
}
```

Обязательные поля: `name`, `author`, `description`.

## Обновить локальные скиллы

```bash
python cli/skill_exchange.py update
```

Выполняет `git pull` и переустанавливает все ранее установленные скиллы.

## Как работает pre-commit hook

При каждом `git commit` хук автоматически:
1. Сканирует все папки в `skills/`
2. Читает `meta.json` каждого скилла
3. Перегенерирует `skills/index.json`
4. Перегенерирует `README.md` с таблицей каталога
5. Добавляет оба файла в коммит

Тебе ничего делать не нужно — каталог всегда актуален.
```

- [ ] **Step 2: Запустить все тесты финально**

```bash
pytest -v
```

Ожидаемый вывод: все тесты `PASSED`, нет ошибок.

- [ ] **Step 3: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs: add CONTRIBUTING.md with full team guide"
```

---

## Self-Review Checklist

- [x] **Spec coverage:**
  - `skills/<name>/{skill.md,meta.json,README.md}` — Task 9
  - `skills/index.json` авто-генерация — Tasks 3, 7
  - CLI все команды — Tasks 4, 5, 6
  - `install.sh` / `install.ps1` — Task 8
  - Pre-commit hook — Task 7
  - Главный `README.md` авто-генерация — Tasks 3, 7
  - `CONTRIBUTING.md` — Task 10
  - Поддержка Windows + Mac/Linux — Tasks 5, 8
  - Claude Desktop best effort — Task 4 (`cmd_install --desktop`)
- [x] **Нет плейсхолдеров** — весь код полный
- [x] **Типы согласованы** — `scan_skills()` → `list`, `write_index(list)`, `generate_readme(list)` везде одинаково
