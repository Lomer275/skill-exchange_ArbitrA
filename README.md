# Skill Exchange ArbitrA

Внутренняя библиотека Claude Code скиллов для команды.

## Быстрый старт

1. Клонируй репо: `git clone <url>`
2. Настрой путь установки: `python cli/skill_exchange.py config --set-path /твой/путь/к/plugins`
3. Установи скилл: `python cli/skill_exchange.py install <name>`
4. Перезапусти Claude Code

## Каталог скиллов

| Имя | Автор | Теги | Описание |
|-----|-------|------|----------|

## Добавить свой скилл

```bash
python cli/skill_exchange.py new my-skill-name
# Отредактируй skills/my-skill-name/{skill.md,meta.json,README.md}
git add skills/my-skill-name
git commit -m 'feat: add my-skill-name'
git push
```

Подробнее: [CONTRIBUTING.md](CONTRIBUTING.md)

> _Этот файл авто-генерируется pre-commit hook'ом. Не редактируй вручную._
