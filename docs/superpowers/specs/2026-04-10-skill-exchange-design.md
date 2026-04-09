# Skill Exchange ArbitrA — Design Spec

**Date:** 2026-04-10  
**Status:** Approved  

---

## Overview

Внутренняя библиотека Claude Code скиллов для команды из 4–6 человек. Git-репозиторий с каталогом готовых скиллов, CLI-инструментом для установки и управления, и автоматизацией поддержания каталога в актуальном состоянии.

---

## Goals

- Любой из 4–6 сотрудников может добавить скилл одним `git push`
- Любой может найти и установить скилл одной командой
- Каталог всегда актуален без ручного обновления
- Работает на Windows и Mac/Linux
- Поддержка трёх сценариев: глобальные скиллы, скиллы проекта, Claude Desktop (best effort)

---

## Repository Structure

```
skill-exchange_ArbitrA/
├── skills/
│   ├── index.json              # авто-генерируемый каталог всех скиллов
│   └── <skill-name>/
│       ├── skill.md            # сам скилл (контент для Claude Code)
│       ├── meta.json           # метаданные скилла
│       └── README.md           # описание + инструкции по установке
├── cli/
│   └── skill_exchange.py       # CLI-инструмент (Python, кросс-платформа)
├── scripts/
│   ├── install.sh              # альтернативная установка скилла вручную (без CLI/Python)
│   └── install.ps1             # то же для Windows PowerShell
├── hooks/
│   └── pre-commit              # авто-обновление index.json и README
├── CONTRIBUTING.md             # гайд для команды по добавлению скиллов
└── README.md                   # главный каталог (авто-генерируется)
```

---

## Skill Format

Каждый скилл — отдельная папка в `skills/` с тремя файлами.

### `meta.json`

```json
{
  "name": "git-commit-helper",
  "display_name": "Git Commit Helper",
  "author": "ivan",
  "version": "1.0.0",
  "description": "Помогает писать осмысленные коммиты",
  "tags": ["git", "workflow"],
  "created": "2026-04-10"
}
```

### `skill.md`

Контент скилла в формате Claude Code — markdown с инструкциями для агента.

### `README.md` (per-skill template)

```markdown
# <Название скилла>

## Что делает
...

## Установка
```bash
skill-exchange install <name>
```
Или вручную: скопировать папку в целевую директорию плагинов.

## Использование
...

## Автор
...
```

---

## CLI (`skill_exchange.py`)

Python-скрипт, кросс-платформенный. Требует Python 3.8+. Вызывается как `python cli/skill_exchange.py <command>`. Главный README описывает как добавить алиас `skill-exchange` для удобства (опционально).

### Команды

| Команда | Описание |
|---|---|
| `list` | Показать все скиллы с описанием |
| `list --tag <tag>` | Фильтр по тегу |
| `install <name>` | Установить в путь из конфига |
| `install <name> --global` | Установить в `~/.claude/plugins/` |
| `install <name> --project` | Установить в `./.claude/plugins/` |
| `install <name> --path <path>` | Установить в произвольный путь |
| `install <name> --desktop` | Скопировать README в буфер обмена (Claude Desktop) |
| `config --set-path <path>` | Сохранить дефолтный путь установки |
| `new <name>` | Создать папку нового скилла с шаблонами |
| `update` | `git pull` + переустановить все установленные скиллы |
| `setup-hooks` | Установить pre-commit hook в текущем репо |

### Локальный конфиг

Хранится в `~/.skill-exchange/config.json`:

```json
{
  "default_path": "~/.claude/plugins/",
  "installed": ["git-commit-helper", "code-reviewer"]
}
```

### Claude Desktop (best effort)

`skill-exchange install <name> --desktop` копирует содержимое `README.md` скилла в буфер обмена с инструкцией вставить в системный промпт Claude Desktop Project.

---

## Automation (pre-commit hook)

Хук `hooks/pre-commit` запускается автоматически перед каждым коммитом:

1. Сканирует все папки в `skills/`
2. Читает `meta.json` каждого скилла
3. Перегенерирует `skills/index.json`
4. Перегенерирует главный `README.md` (таблицу каталога)
5. Добавляет оба файла в коммит (`git add`)

Установка: `skill-exchange setup-hooks`

---

## Documentation

### Главный `README.md`
- Таблица всех скиллов: имя, автор, теги, описание
- Раздел "Быстрый старт" — установить CLI и получить первый скилл за 3 шага
- Раздел "Добавить свой скилл"

### `CONTRIBUTING.md`
- Как клонировать репо
- Как создать скилл через `skill-exchange new`
- Требования к `meta.json`
- Как работает pre-commit hook

### Per-skill `README.md`
- Описание, инструкции установки, примеры использования, автор

---

## Out of Scope

- Pull request / ревью перед публикацией скилла
- Полноценная интеграция с Claude Desktop
- Рейтинги, отзывы, лайки
- Веб-интерфейс
