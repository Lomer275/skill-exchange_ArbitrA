# Skill Exchange ArbitrA

Внутренняя библиотека Claude Code скиллов команды ArbitrA.
Распространяется как Claude Code marketplace.

## Установка (рекомендованный путь)

В Claude Code:

```
/plugin marketplace add Lomer275/skill-exchange_ArbitrA
/plugin install team-skills@skill-exchange
```

После установки все скиллы доступны как `/team-skills:<имя-скилла>`.

## Альтернатива: личная установка одного скилла через CLI

```bash
git clone https://github.com/Lomer275/skill-exchange_ArbitrA.git
cd skill-exchange_ArbitrA
python cli/skill_exchange.py install <имя-скилла>
```

Копирует `SKILL.md` в `~/.claude/skills/<имя>/`. Скилл доступен как `/<имя>`.

## Каталог скиллов

| Имя | Автор | Теги | Описание |
|-----|-------|------|----------|
| [example-skill](plugins/team-skills/skills/example-skill/README.md) | team | example, template | Демонстрационный скилл — шаблон для создания своих |

## Добавить свой скилл

```bash
python cli/skill_exchange.py new my-skill-name
# Отредактируй plugins/team-skills/skills/my-skill-name/{SKILL.md,meta.json,README.md}
git add plugins/team-skills/skills/my-skill-name
git commit -m 'feat: add my-skill-name'
git push
```

Подробнее: [CONTRIBUTING.md](CONTRIBUTING.md)

> _Этот файл авто-генерируется pre-commit hook'ом. Не редактируй вручную._
