---
name: spec-writer
description: >
  Creates SUP-project documents: specifications (S), tasks (T), and business requirements (BR)
  following all project conventions. Reads guides at runtime — does not rely on memory.
  Use when the user says "/sup-spec-writer", "создай спеку", "создай задачу",
  "новая спека", "новая задача", "напиши спецификацию", "создай BR",
  "задекомпозируй спеку на задачи".
---

# Sup-Spec-Writer Skill

Creates one document per invocation (a spec, task, or BR) with correct numbering and structure.
Reads guides at runtime — does not rely on memory. Skeleton only — the user fills in the content.

---

## Inputs

- `/sup-spec-writer` — ask the user for the document type
- `/sup-spec-writer spec "Title"` — create a specification
- `/sup-spec-writer task "Title" S03` — create a task (linked to a spec)
- `/sup-spec-writer br "Title"` — create a business requirement
- "создай задачу для S05" — create a task linked to spec S05
- "задекомпозируй спеку S04 на задачи" — create a single task (not all at once — one per invocation)

---

## Algorithm

### Step 1 — Determine the document type

If the type is not explicitly specified — **ask one question**:

```
Какой документ создать?
1. Спецификация (S) — docs/2. SUP-specifications/
2. Задача (T) — docs/3. SUP-tasks/
3. Бизнес-требование (BR) — docs/1. SUP-business requirements/
```

Do not proceed until the user answers.

### Step 2 — Read the guides (MANDATORY at runtime)

**Always read** (regardless of type):
```
docs/4. SUP-guides/doc_conventions.md
```

**Additionally, depending on the type:**
- If type=S → read `docs/4. SUP-guides/specifications_guide.md`
- If type=T → read `docs/4. SUP-guides/task_decomposition_guide.md`
- If type=BR → read `docs/4. SUP-guides/business_requirements_template.md`

**Never skip this step** — do not rely on cached knowledge.

### Step 3 — Determine the next number

#### For a specification (SNN):

Run a glob over both directories:
```
glob docs/2. SUP-specifications/S*.md
glob docs/backlog/S*.md
```

From all matched file names, extract the numbers after `S` (two-digit format).
Find the maximum number → next number = max + 1, in two-digit format (`01`, `02`, ..., `10`, `11`).

Example: if S01, S02, S05, S06 are found → next = S07.

#### For a task (TNN):

Run a recursive glob:
```
glob docs/3. SUP-tasks/**/T*.md
```

This covers both current tasks and files in `Done/` (nested folders).
From all matched file names, extract the numbers after `T`.
Find the maximum → next = max + 1, two-digit format.

Example: if T01..T55 are found including Done/ → next = T56.

#### For a business requirement (BRNN):

Run a glob:
```
glob docs/1. SUP-business requirements/SUP-BR*.md
```

From the file names, extract the numbers after `BR`.
Find the maximum → next = max + 1, two-digit format.

### Step 4 — Check for a conflict

If a file with the computed number already exists:
- Tell the user: `Файл SNN уже существует: <путь>`
- Suggest: `Обновить существующий файл или создать новый (следующий номер)?`
- Wait for an answer — do not proceed.

### Step 5 — Clarify missing data (if needed)

If the title was not provided — ask **one question**:
```
Как назвать документ? (используется для имени файла в snake_case)
```

For a task (type=T) — if no spec link is specified:
```
К какой спецификации относится задача? (например, S03)
```

**Ask questions one at a time** — do not ask several at once.

### Step 6 — Build the file name and path

Convert the title into `snake_case`:
- All lowercase
- Spaces and hyphens → underscores
- Remove special characters

**Paths by type:**

| Type | Path |
|-----|------|
| S | `docs/2. SUP-specifications/SNN_<snake_case>.md` |
| T | `docs/3. SUP-tasks/TNN_<snake_case>.md` |
| BR | `docs/1. SUP-business requirements/SUP-BRNN_<snake_case>.md` |

### Step 7 — Create the skeleton file

Create **only a skeleton** — section headings, status, number, empty fields.
Do not fill in the content for the user.
The status of a new document is always = `draft`.

#### Skeleton for a specification (S):

```markdown
# SNN. <Название>

**Статус:** draft
**Дата:** YYYY-MM-DD
**Версия:** 0.1

---

## Цель

<!-- Что решает эта спецификация и для кого -->

## Скоуп

<!-- Что входит / что не входит. Фазы реализации если применимо -->

## Архитектура

<!-- Компоненты, интеграции, потоки данных -->

## Модели данных

<!-- Структуры, поля, типы -->

## Задачи

| # | Задача | Исполнитель | Статус |
|---|--------|-------------|--------|
| T? | ... | - | 🟡 |

## Definition of Done

- [ ] ...

## Связанные документы

- ...
```

#### Skeleton for a task (T):

```markdown
# TNN. <Название>

**Спецификация:** docs/2. SUP-specifications/SNN_<spec_name>.md
**Статус:** draft
**Дата:** YYYY-MM-DD

---

## Описание

<!-- Что нужно сделать и зачем -->

## Детали реализации

<!-- Технические детали, ключевые решения -->

## Критерии приёмки

- [ ] ...

## Связанные файлы

- ...
```

#### Skeleton for a business requirement (BR):

```markdown
# SUP-BRNN. <Название>

**Статус:** draft
**Дата:** YYYY-MM-DD
**Версия:** 0.1

---

## Контекст и проблема

<!-- Бизнес-контекст, текущая боль -->

## Цели

<!-- Измеримые цели (OKR-стиль если применимо) -->

## Требования

### Функциональные

- ...

### Нефункциональные

- ...

## Сценарии использования

<!-- Use cases, пользовательские сценарии -->

## Ограничения и допущения

- ...

## Связанные документы

- ...
```

### Step 8 — Report

After creating the file, output a summary in the format:

```
✅ Создан файл: docs/2. SUP-specifications/S07_my_feature.md

Структура:
  - Статус: draft
  - Номер: S07
  - Связанные задачи: не созданы

Следующие шаги:
  - Заполни секции контентом
  - При готовности запусти /sup-spec-writer для задач (TNN)
  - Для закрытия задачи запусти /accept
```

Adapt "Следующие шаги" to the document type:
- For BR → suggest creating a linked spec
- For T → remind about the spec link and /accept

---

## Rules

- **One invocation = one file.** Never create two documents in a single invocation.
- **Skeleton only.** Do not fill in the content for the user — structure only.
- **The status of a new document is always `draft`.**
- **Always read the guides at runtime** (Step 2) — do not rely on memory or previous reads.
- **Numbering is always two-digit:** 01, 02, ..., 10, 11, 12...
- **TNN: scan recursively including Done/.** The maximum number across all files — not only active tasks.
- **SNN: scan both specs/ and backlog/.** Both sources.
- If the type is not specified — ask first, do not guess.
- If content clarifications are needed — ask **one question** at a time.
- If a file with that number already exists — report it and ask what to do.
- The date in the document is always today (`currentDate` from the system context).
