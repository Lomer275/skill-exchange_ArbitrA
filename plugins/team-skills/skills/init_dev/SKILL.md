---
name: init_dev
description: >
  Creates the base documentation structure for a new project: docs/ folders, guides,
  SUP-architecture.md, SUP-HANDOFF.md, SUP-CHANGELOG.md, CLAUDE.md.
  Use when the user says "/init_dev", "инициализируй проект",
  "создай структуру документации", "новый проект", "init project docs".
---

# Init Dev Skill

Creates a standard project documentation structure. A universal template.

---

## Algorithm

### Step 1 — Gather information about the project

Ask the user the following questions **in a single message**:

```
Для инициализации проекта нужно несколько деталей:

1. **Префикс проекта** — аббревиатура для именования файлов (например: SUP, PAY, CRM)
2. **Название проекта** — полное название (например: SupportBots, PaymentService)
3. **Описание** — 1–2 предложения: что делает система, для кого
4. **Стек** — язык, фреймворк, БД, очереди (например: Python/Django, PostgreSQL, Redis)
5. **Основные компоненты** — перечисли модули/сервисы системы (например: API, бот, CRM-интеграция)
6. **Инфраструктура** — как деплоится (например: VPS + Nginx + Gunicorn, Docker, k8s)
7. **Команда** — имена и роли участников
```

Wait for the user's response before continuing.

---

### Step 2 — Determine the numbering

Check existing files:
- `glob docs/2. SUP-specifications/**/*.md` → find the maximum SNN
- `glob docs/3. SUP-tasks/**/*.md` → find the maximum TNN

If there are no files — start from S01 / T01.
If there are — the next number = max + 1.

---

### Step 3 — Create the folder structure

```
docs/
├── 1. PREFIX-business requirements/
├── 2. PREFIX-specifications/
├── 3. PREFIX-tasks/
│   └── Done/
├── 4. PREFIX-guides/
├── 5. PREFIX-unsorted/
└── backlog/
```

Replace `PREFIX` with the prefix from step 1.

Create a `.gitkeep` in empty folders so that git tracks them.

---

### Step 4 — Copy the guides

Read each file from `docs/4. SUP-guides/` of the current repo and write it to `docs/4. PREFIX-guides/` of the new project:

- `doc_conventions.md`
- `specifications_guide.md`
- `task_decomposition_guide.md`
- `versioning_guidelines.md`
- `business_requirements_template.md`
- `architect_files_selection_guide.md`
- `project_readme_guide.md`

When copying, replace all mentions of `SUP` with the new PREFIX in the text of the guides.

---

### Step 5 — Create SUP-architecture.md

Use the user's answers from step 1. Create the file `PREFIX-architecture.md`:

```markdown
# PREFIX-architecture

**Статус:** draft
**Дата:** YYYY-MM-DD
**Версия:** 0.1

---

## System Overview

<описание из шага 1>

## Components

<для каждого компонента из шага 1>
### <Название компонента> (`папка/`)
- **Технология:** <стек>
- **Ответственность:** <что делает>

## Infrastructure

<из ответа об инфраструктуре>

## Связанные документы

- [README.md](README.md) — обзор проекта
- [PREFIX-HANDOFF.md](PREFIX-HANDOFF.md) — текущее состояние
```

---

### Step 6 — Create PREFIX-HANDOFF.md

```markdown
# PREFIX-HANDOFF — Текущее состояние

**Дата обновления:** YYYY-MM-DD

---

## Текущее состояние

<краткое описание текущего статуса проекта — заполни на основе описания из шага 1>

**Стек:** <из шага 1>

## OKR

> Заполнить после определения целей

## Следующие шаги

> Задачи появятся после создания первой спецификации

## Текущая функциональность

> Описать после первого релиза

## Команда

| Имя | Роль |
|-----|------|
<из шага 1>

## Связанные документы

- [README.md](README.md) — обзор проекта
- [PREFIX-architecture.md](PREFIX-architecture.md) — архитектура
- [PREFIX-CHANGELOG.md](PREFIX-CHANGELOG.md) — история изменений
```

---

### Step 7 — Create PREFIX-CHANGELOG.md

```markdown
# PREFIX-CHANGELOG

## [Не выпущено]

### Added
- Инициализация документации проекта

---

## [0.1.0] — YYYY-MM-DD

### Added
- Базовая структура документации
- Гайды по работе с проектом
```

---

### Step 8 — Create CLAUDE.md

```markdown
# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Проект

<название и описание из шага 1>

## Репозиторий

> Описать: только документация или монорепо с кодом

## Структура документации

```
docs/
├── 1. PREFIX-business requirements/
├── 2. PREFIX-specifications/
├── 3. PREFIX-tasks/
│   └── Done/
├── 4. PREFIX-guides/
├── 5. PREFIX-unsorted/
└── backlog/
```

Ключевые файлы корня:
- `PREFIX-HANDOFF.md` — текущий статус, задачи, приоритеты
- `PREFIX-architecture.md` — архитектура системы
- `PREFIX-CHANGELOG.md` — журнал изменений

## Гайды (docs/4. PREFIX-guides/)

| Файл | Назначение |
|------|-----------|
| `doc_conventions.md` | Правила именования файлов и структуры |
| `specifications_guide.md` | Как писать спецификации |
| `task_decomposition_guide.md` | Декомпозиция спеков на задачи |
| `versioning_guidelines.md` | SemVer + Conventional Commits |

**Всегда читай эти гайды перед созданием новых документов.**

## Правила именования

- Спецификации: `SNN_<snake_case>.md` → `docs/2. PREFIX-specifications/`
- Задачи: `TNN_<snake_case>.md` → `docs/3. PREFIX-tasks/`
- Нумерация: последовательная, двузначная (`01`, `02`, ...)
- Статусы: `draft`, `active`, `done`, `deprecated`

## Команда

| Имя | Роль |
|-----|------|
<из шага 1>

## Tech Stack

<из шага 1>
```

---

### Step 9 — Report

Output the summary:

```
✅ Проект PREFIX инициализирован

Создана структура:
  docs/1. PREFIX-business requirements/
  docs/2. PREFIX-specifications/
  docs/3. PREFIX-tasks/Done/
  docs/4. PREFIX-guides/  (N файлов гайдов скопировано)
  docs/5. PREFIX-unsorted/
  docs/backlog/

Созданы файлы:
  PREFIX-architecture.md
  PREFIX-HANDOFF.md
  PREFIX-CHANGELOG.md
  CLAUDE.md

Следующий шаг: создай первую спецификацию S01 командой или вручную.
```

---

## Rules

- Always wait for the user's response before creating files
- Do not overwrite existing files without explicit confirmation
- If the `docs/` folder already partially exists — create only what is missing
- The date in files is always today's (`currentDate` from the system context)
