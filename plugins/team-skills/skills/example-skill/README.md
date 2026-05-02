# Example Skill

Демонстрационный скилл — шаблон для создания своих.

## Что делает

Показывает правильную структуру скилла. Используй как отправную точку при создании нового скилла.

## Установка

**Через marketplace (рекомендуется):**

```
/plugin marketplace add Lomer275/skill-exchange_ArbitrA
/plugin install team-skills@skill-exchange
```

После этого скилл доступен как `/team-skills:example-skill`.

**Через CLI (личная установка):**

```bash
python cli/skill_exchange.py install example-skill
```

Скопирует `SKILL.md` в `~/.claude/skills/example-skill/`. Доступ как `/example-skill`.

## Использование

Используй как шаблон: скопируй папку `plugins/team-skills/skills/example-skill`, переименуй, отредактируй `SKILL.md`, `meta.json` и `README.md`.

## Автор

team
