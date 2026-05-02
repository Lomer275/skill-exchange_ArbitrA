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

SKILL_FILES_TO_INSTALL = ("SKILL.md", "README.md")


# ── helpers ────────────────────────────────────────────────────────────────────

def _resolve_target(args, config) -> Path:
    """Determine where install/uninstall should operate."""
    if getattr(args, "path", None):
        return Path(args.path).expanduser()
    if getattr(args, "global_", False):
        return Path.home() / ".claude" / "skills"
    if getattr(args, "project", False):
        return Path.cwd() / ".claude" / "skills"
    return Path(config["default_path"]).expanduser()


# ── list ──────────────────────────────────────────────────────────────────────

def cmd_list(args):
    index_file = idx_module.INDEX_FILE
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
    try:
        idx_module.validate_name(args.name)
    except idx_module.InvalidSkillNameError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(2)
    config = cfg_module.load_config()
    skill_src = idx_module.SKILLS_DIR / args.name
    if not skill_src.exists():
        print(f"Скилл '{args.name}' не найден в репо.")
        sys.exit(1)

    if args.desktop:
        readme = skill_src / "README.md"
        skill_md = skill_src / "SKILL.md"
        text = (readme.read_text(encoding="utf-8") if readme.exists()
                else skill_md.read_text(encoding="utf-8") if skill_md.exists()
                else "")
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

    target_dir = _resolve_target(args, config)
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / args.name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    copied = []
    for filename in SKILL_FILES_TO_INSTALL:
        src = skill_src / filename
        if src.exists():
            shutil.copy(src, dest / filename)
            copied.append(filename)
    if "SKILL.md" not in copied:
        print(f"Ошибка: в '{args.name}' отсутствует SKILL.md — скилл невалиден.")
        shutil.rmtree(dest)
        sys.exit(1)
    print(f"Скилл '{args.name}' установлен в {dest}")
    print(f"Активируй через перезапуск Claude Code. Скилл будет доступен как /{args.name}")

    if args.name not in config["installed"]:
        config["installed"].append(args.name)
        cfg_module.save_config(config)


# ── uninstall ─────────────────────────────────────────────────────────────────

def cmd_uninstall(args):
    try:
        idx_module.validate_name(args.name)
    except idx_module.InvalidSkillNameError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(2)
    config = cfg_module.load_config()
    target_dir = _resolve_target(args, config)
    dest = target_dir / args.name

    if not dest.exists():
        print(f"Скилл '{args.name}' не установлен в {target_dir}")
    elif not (dest / "SKILL.md").is_file():
        print(
            f"Ошибка: {dest} не содержит SKILL.md — это не папка скилла. "
            f"Удаление отклонено для безопасности.",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        shutil.rmtree(dest)
        print(f"Скилл '{args.name}' удалён из {dest}")

    if args.name in config["installed"]:
        config["installed"].remove(args.name)
        cfg_module.save_config(config)
        print("Удалён из списка установленных.")


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
    try:
        idx_module.validate_name(args.name)
    except idx_module.InvalidSkillNameError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(2)
    skill_dir = idx_module.SKILLS_DIR / args.name
    if skill_dir.exists():
        print(f"Скилл '{args.name}' уже существует.")
        sys.exit(1)
    skill_dir.mkdir(parents=True)

    today = date.today().isoformat()
    author = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    display_name = args.name.replace("-", " ").title()
    description = "Опиши что делает скилл и когда его использовать (это поле читает Claude для авто-активации)"

    meta = {
        "name": args.name,
        "display_name": display_name,
        "author": author,
        "version": "1.0.0",
        "description": description,
        "tags": [],
        "created": today,
    }
    (skill_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (skill_dir / "SKILL.md").write_text(
        f"---\n"
        f"name: {args.name}\n"
        f"description: {description}\n"
        f"---\n\n"
        f"# {display_name}\n\n"
        f"Опиши что делает скилл. Это содержимое читается Claude при активации.\n\n"
        f"## Роль\n\nТы — [роль]. Твоя задача — [цель].\n\n"
        f"## Правила\n\n- Правило 1\n- Правило 2\n",
        encoding="utf-8",
    )
    (skill_dir / "README.md").write_text(
        f"# {display_name}\n\n"
        f"## Что делает\n\nОпиши скилл.\n\n"
        f"## Установка\n\n"
        f"**Через marketplace:**\n\n"
        f"```\n/plugin marketplace add {idx_module.GITHUB_REPO}\n"
        f"/plugin install {idx_module.PLUGIN_NAME}@{idx_module.MARKETPLACE_NAME}\n```\n\n"
        f"Доступ как `/{idx_module.PLUGIN_NAME}:{args.name}`.\n\n"
        f"**Через CLI (личная установка):**\n\n"
        f"```bash\npython cli/skill_exchange.py install {args.name}\n```\n\n"
        f"Доступ как `/{args.name}`.\n\n"
        f"## Использование\n\nОпиши как использовать.\n\n"
        f"## Автор\n\n{author}\n",
        encoding="utf-8",
    )
    try:
        rel = skill_dir.relative_to(REPO_ROOT)
    except ValueError:
        rel = skill_dir
    print(f"Скилл '{args.name}' создан в {skill_dir}")
    print(f"Отредактируй: {rel}/{{SKILL.md,meta.json,README.md}}")
    print(f"Затем: git add {rel} && git commit && git push")


# ── update ─────────────────────────────────────────────────────────────────────

def cmd_update(args):
    print("Обновляем репо...")
    subprocess.run(["git", "pull"], cwd=REPO_ROOT, check=True)
    config = cfg_module.load_config()
    target_dir = Path(config["default_path"]).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)

    for name in list(config.get("installed", [])):
        print(f"Переустанавливаем {name}...")
        skill_src = idx_module.SKILLS_DIR / name
        if not skill_src.exists():
            print(f"  Скилл '{name}' не найден в репо, пропускаем.")
            continue
        dest = target_dir / name
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for filename in SKILL_FILES_TO_INSTALL:
            src = skill_src / filename
            if src.exists():
                shutil.copy(src, dest / filename)
        print(f"  Установлен в {dest}")
    print("Готово.")


# ── validate ──────────────────────────────────────────────────────────────────

def cmd_validate(args):
    errors = idx_module.validate_all()
    if errors:
        print("Ошибки валидации:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)
    print("Все скиллы валидны.")


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
    print("Теперь при каждом коммите каталог скиллов будет валидироваться и обновляться автоматически.")


# ── argparse ───────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill-exchange",
        description="Менеджер Claude Code скиллов команды",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="Показать все скиллы")
    p_list.add_argument("--tag", help="Фильтр по тегу")

    p_install = sub.add_parser("install", help="Установить скилл (личная установка в ~/.claude/skills/)")
    p_install.add_argument("name", help="Имя скилла")
    p_install.add_argument("--global", dest="global_", action="store_true",
                           help="Установить в ~/.claude/skills/")
    p_install.add_argument("--project", action="store_true",
                           help="Установить в ./.claude/skills/")
    p_install.add_argument("--path", help="Установить в произвольный путь")
    p_install.add_argument("--desktop", action="store_true",
                           help="Скопировать README в буфер (Claude Desktop)")

    p_uninstall = sub.add_parser("uninstall", help="Удалить установленный скилл")
    p_uninstall.add_argument("name", help="Имя скилла")
    p_uninstall.add_argument("--global", dest="global_", action="store_true",
                             help="Удалить из ~/.claude/skills/")
    p_uninstall.add_argument("--project", action="store_true",
                             help="Удалить из ./.claude/skills/")
    p_uninstall.add_argument("--path", help="Удалить из произвольного пути")

    p_cfg = sub.add_parser("config", help="Настройки CLI")
    p_cfg.add_argument("--set-path", metavar="PATH", help="Сохранить дефолтный путь установки")

    p_new = sub.add_parser("new", help="Создать новый скилл с шаблонами")
    p_new.add_argument("name", help="Имя нового скилла (kebab-case)")

    sub.add_parser("update", help="git pull + переустановить все установленные скиллы")
    sub.add_parser("validate", help="Проверить все скиллы (meta.json + frontmatter SKILL.md)")
    sub.add_parser("setup-hooks", help="Установить git pre-commit hook")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    {
        "list": cmd_list,
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "config": cmd_config,
        "new": cmd_new,
        "update": cmd_update,
        "validate": cmd_validate,
        "setup-hooks": cmd_setup_hooks,
    }[args.command](args)


if __name__ == "__main__":
    main()
