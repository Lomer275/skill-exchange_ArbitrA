# Skill Exchange ArbitrA

Внутренняя библиотека Claude Code скиллов для команды.

## Быстрый старт

1. Клонируй репо: `git clone https://github.com/Lomer275/skill-exchange_ArbitrA.git`
2. Установи pre-commit hook: `python cli/skill_exchange.py setup-hooks`
3. Укажи путь к плагинам: `python cli/skill_exchange.py config --set-path <путь>`
   - Windows: `C:\Users\<имя>\.claude\plugins`
   - Mac/Linux: `~/.claude/plugins`
4. Установи скилл: `python cli/skill_exchange.py install <name>`
5. Перезапусти Claude Code

## Каталог скиллов

| Имя | Автор | Теги | Описание |
|-----|-------|------|----------|
| [example-skill](skills/example-skill/README.md) | team | example, template | Демонстрационный скилл — шаблон для создания своих |

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
