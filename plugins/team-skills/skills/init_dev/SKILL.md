---
name: init_dev
description: >
  Creates the base documentation structure for a new project: docs/ folders, guides,
  PREFIX-architecture.md, PREFIX-HANDOFF.md, PREFIX-CHANGELOG.md, CLAUDE.md.
  Use when the user says "/init_dev", "инициализируй проект",
  "создай структуру документации", "новый проект", "init project docs".
  If the project or the user has its own `init_dev` skill, that one takes precedence — use this one only when the user typed `/team-skills:init_dev` or no such skill exists.
---

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:init_dev` and a skill named `init_dev` exists in the project (`.claude/skills/init_dev/SKILL.md`) or in the user's skills (`~/.claude/skills/init_dev/SKILL.md`), stop: tell the user that their own `/init_dev` takes precedence, and do nothing else.

# Init Dev Skill

Creates a standard project documentation structure. A universal template.

---

## Algorithm

### Step 1 — Gather information about the project

Ask the user the following questions **in a single message**:

```
Для инициализации проекта нужно несколько деталей:

1. **Префикс проекта** — аббревиатура для именования файлов (например: APP, PAY, CRM)
2. **Название проекта** — полное название (например: ProjectHub, PaymentService)
3. **Описание** — 1–2 предложения: что делает система, для кого
4. **Стек** — язык, фреймворк, БД, очереди (например: Python/Django, PostgreSQL, Redis)
5. **Основные компоненты** — перечисли модули/сервисы системы (например: API, бот, CRM-интеграция)
6. **Инфраструктура** — как деплоится (например: VPS + Nginx + Gunicorn, Docker, k8s)
7. **Команда** — имена и роли участников
```

Wait for the user's response before continuing.

---

### Step 2 — Determine the numbering

If a profile already exists, read it before any writes and use its configured paths; do not overwrite its layout. Otherwise the following `PREFIX` paths are the new layout chosen in Step 1, not discovery defaults for existing projects.

Check existing files:
- `glob docs/2. PREFIX-specifications/**/*.md` → find the maximum SNN
- `glob docs/3. PREFIX-tasks/**/*.md` → find the maximum TNN

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

Replace `PREFIX` with the prefix from step 1 only for a new profile. If the target already has a profile, use its configured document directories instead of this example tree. Before creating anything, check the existing profile against the requested layout; stop on conflicts.

Create a `.gitkeep` in empty folders so that git tracks them.

---

### Step 4 — Create the profile and copy available guides

Read the bundled `templates/team-skills.json` relative to this skill's directory.
Replace only the `PREFIX` placeholders with the prefix chosen in Step 1, using
JSON serialization so the result remains valid JSON. Create
`.claude/team-skills.json` in the target repository; all document paths are
relative to that repository root. This file is the sole source of project paths
for the other team-skills document workflows. Validate `version: 1`, the key
structure, and that each path points to the structure just created. Keep
`commands.push` as `/team-skills:safe-push` and `commands.spec_writer` as
`/team-skills:spec-writer` unless the user supplies their project equivalents.
`shared_paths` starts empty: ask the project owner which shared code paths need
worktree isolation and record only confirmed paths. Never infer them from another
project. Do not overwrite an existing profile without explicit confirmation;
read it first and preserve its chosen paths, creating only missing structure.
If it conflicts with the newly chosen layout, stop and report the conflict.

The catalog does not bundle documentation guides. If the project has an existing
profile with `docs.guides`, or the user supplies a guide source directory, copy
available guides from that source to the new profile's `docs.guides` directory.
Read before copying, do not overwrite existing files without confirmation, and
do not replace arbitrary project names in guide prose. Substitute only explicit
template placeholders. Useful guide names are:

- `doc_conventions.md`
- `specifications_guide.md`
- `task_decomposition_guide.md`
- `versioning_guidelines.md`
- `business_requirements_template.md`
- `architect_files_selection_guide.md`
- `project_readme_guide.md`

If a source or guide is absent, skip it and list what is missing in the report.
Do not claim those guides were installed. Before invoking a skill that requires
a missing guide, ask the owner to provide it. The profile format is documented in
the catalog's `docs/team-skills-profile.md`.

---

### Step 5 — Create PREFIX-architecture.md

Use the user's answers from step 1. Create the file at the profile's `architecture` path (for a new profile: `PREFIX-architecture.md`):

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

### Step 6 — Create the file at the profile's `handoff` path

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

### Step 7 — Create the file at the profile's `changelog` path

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

The examples below use the new PREFIX layout. In all generated documents, resolve links and directory references from the actual profile, including existing custom layouts.

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
  .claude/team-skills.json

Укажи отсутствующие гайды и пропущенные файлы.
Следующий шаг: создай первую спецификацию S01 командой или вручную.
```

---

## Rules

- Always wait for the user's response before creating files
- Do not overwrite existing files without explicit confirmation
- If the `docs/` folder already partially exists — create only what is missing
- The date in files is always today's (`currentDate` from the system context)
