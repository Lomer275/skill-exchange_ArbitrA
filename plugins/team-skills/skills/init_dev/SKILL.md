---
name: init_dev
description: "Создаёт базовую структуру документации для нового проекта: папки docs/, гайды, architecture.md, HANDOFF.md, CHANGELOG.md, CLAUDE.md. Используй когда пользователь говорит '/init_dev', 'инициализируй проект',"
---
# Init Dev Skill

Создаёт стандартную структуру документации проекта. Универсальный шаблон.

---

## Алгоритм

### Шаг 1 — Собрать информацию о проекте

Задай пользователю следующие вопросы **одним сообщением**:

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

Жди ответа пользователя перед продолжением.

---

### Шаг 2 — Определить нумерацию

Проверь существующие файлы:
- `glob docs/specifications/**/*.md` → найди максимальный SNN
- `glob docs/tasks/**/*.md` → найди максимальный TNN

Если файлов нет — начинай с S01 / T01.
Если есть — следующий номер = max + 1.

---

### Шаг 3 — Создать структуру папок

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

Замени `PREFIX` на префикс из шага 1.

Создай `.gitkeep` в пустых папках чтобы git их отслеживал.

---

### Шаг 4 — Скопировать гайды

Прочитай каждый файл из `docs/guides/` текущего репо и запиши в `docs/4. PREFIX-guides/` нового проекта:

- `doc_conventions.md`
- `specifications_guide.md`
- `task_decomposition_guide.md`
- `versioning_guidelines.md`
- `business_requirements_template.md`
- `architect_files_selection_guide.md`
- `project_readme_guide.md`

При копировании замени все упоминания `PROJECT` на новый PREFIX в тексте гайдов.

---

### Шаг 5 — Создать architecture.md

Используй ответы пользователя из шага 1. Создай файл `PREFIX-architecture.md`:

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

### Шаг 6 — Создать PREFIX-HANDOFF.md

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

### Шаг 7 — Создать PREFIX-CHANGELOG.md

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

### Шаг 8 — Создать CLAUDE.md

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

### Шаг 9 — Отчёт

Выведи итог:

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

## Правила

- Всегда жди ответа пользователя перед созданием файлов
- Не перезаписывай существующие файлы без явного подтверждения
- Если папка `docs/` уже частично существует — создавай только то чего нет
- Дата в файлах — всегда сегодняшняя (`currentDate` из системного контекста)
