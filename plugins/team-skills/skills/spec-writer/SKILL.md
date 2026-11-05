---
name: spec-writer
description: >
  Creates project documents: specifications (S), tasks (T), and business requirements (BR)
  following all project conventions. Reads guides at runtime — does not rely on memory.
  Use when the user says "/spec-writer", "создай спеку", "создай задачу",
  "новая спека", "новая задача", "напиши спецификацию", "создай BR",
  "задекомпозируй спеку на задачи".
  If the project or the user has its own `spec-writer` skill, that one takes precedence — use this one only when the user typed `/team-skills:spec-writer` or no such skill exists.
---

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:spec-writer` and a skill named `spec-writer` exists in the project (`.claude/skills/spec-writer/SKILL.md`) or in the user's skills (`~/.claude/skills/spec-writer/SKILL.md`), stop: tell the user that their own `/spec-writer` takes precedence, and do nothing else.

## Project profile (mandatory)

After Step 0 and before any other action, read `.claude/team-skills.json` from the repository root. Require format `version: 1` and these keys: `docs.guides`, `commands.spec_writer`; additionally `docs.specifications` for S or T, `docs.tasks`, `docs.tasks_done`, `handoff`, `changelog` for T, and `docs.business_requirements`, `prefix` for BR. Read only the keys needed for this invocation. A missing file, unsupported version, or missing/empty required key means stop before reading or changing project documents: name the missing file/key and point to `team-skills:init_dev` and the catalog's `docs/team-skills-profile.md`. Never infer a prefix or substitute project paths.

If the document type is unknown, validate the common keys first, ask for the type in Step 1, then validate its additional keys before proceeding.

In this skill, `{key}` means the value of that profile key; resolve paths relative to the repository root. These are notation, not literal shell variables: substitute and shell-quote the resolved values before executing commands. Paths must stay inside the repository.

# Spec Writer Skill

Creates one document per invocation (a spec, task, or BR) with correct numbering and structure.
Reads guides at runtime — does not rely on memory. Skeleton only — the user fills in the content.

---

## Inputs

- `/spec-writer` — ask the user for the document type
- `/spec-writer spec "Title"` — create a specification
- `/spec-writer task "Title" S03` — create a task (linked to a spec)
- `/spec-writer br "Title"` — create a business requirement
- "создай задачу для S05" — create a task linked to spec S05
- "задекомпозируй спеку S04 на задачи" — create a single task (not all at once — one per invocation)

---

## Algorithm

### Step 1 — Determine the document type

If the type is not explicitly specified — **ask one question**:

```
Какой документ создать?
1. Specification (S)
2. Task (T)
3. Business requirement (BR)
```

Do not proceed until the user answers.

### Step 2 — Read the guides (MANDATORY at runtime)

**Always read** (regardless of type):
```
{docs.guides}/doc_conventions.md
```

**Additionally, depending on the type:**
- If type=S → read `{docs.guides}/specifications_guide.md`
- If type=T → read `{docs.guides}/task_decomposition_guide.md`
- If type=BR → read `{docs.guides}/business_requirements_template.md`

**Never skip this step** — do not rely on cached knowledge.

### Step 3 — Determine the next number

#### For a specification (SNN):

Scan the configured specification directory recursively, including its backlog subdirectory if present:
```
glob {docs.specifications}/**/S*.md
```

If project documentation mentions specs in a backlog outside this configured directory, stop and request a profile layout that includes that backlog; do not assume its location.

From all matched file names, extract the numbers after `S`.
Find the maximum number → next number = max + 1, at least two digits (`01` … `09`, `10`, … `59`, `100`).

Example: if S01, S02, S05, S06 are found → next = S07.

#### For a task (TNN):

Run a recursive glob:
```
glob {docs.tasks}/**/T*.md
glob {docs.tasks_done}/**/T*.md
```

This covers both current tasks and files in `Done/` (nested folders).
From all matched file names, extract the numbers after `T`.
Find the maximum → next = max + 1, at least two digits.

Example: if the maximum found, including Done/, is T497 → next = T498.

**The file scan is not enough.** A number can be taken before its file exists — in another worktree on an unpushed branch, or reserved in prose («Follow-up T<NN>»). Scan every worktree and grep the candidate:

List worktrees with `git worktree list --porcelain`. In each tree, read that tree's profile and scan its configured `docs.tasks` and `docs.tasks_done` recursively. If a tree's required keys are missing, stop and name the tree/key instead of guessing. Search candidate TNN mentions in the configured task/specification directories, `{handoff}`, and `{changelog}` with `rg`. Shell-quote all resolved paths. Do not create or delete worktrees for this scan.

Take the first number with no file in any tree and no mention in prose.

#### For a business requirement (BRNN):

Run a glob:
```
glob {docs.business_requirements}/{prefix}-BR*.md
```

From the file names, extract the numbers after `BR`.
Find the maximum → next = max + 1, at least two digits.

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
| S | `{docs.specifications}/SNN_<snake_case>.md` |
| T | `{docs.tasks}/TNN_<snake_case>.md` |
| BR | `{docs.business_requirements}/{prefix}-BRNN_<snake_case>.md` |

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

The task status lives in YAML frontmatter when the project's task decomposition guide defines one (as below — check the guide for the exact fields). A project without frontmatter keeps `**Статус:** draft` and `**Дата:** YYYY-MM-DD` lines under `**Спецификация:**` instead.

```markdown
---
spec: SNN_<spec_name>
status: draft
created: YYYY-MM-DD
wave: 1
depends_on: []
---

# TNN. <Название>

**Спецификация:** {docs.specifications}/SNN_<spec_name>.md

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
# {prefix}-BRNN. <Название>

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
✅ Создан файл: {docs.specifications}/S07_my_feature.md

Структура:
  - Статус: draft
  - Номер: S07
  - Связанные задачи: не созданы

Следующие шаги:
  - Заполни секции контентом
  - При готовности запусти {commands.spec_writer} для задач (TNN)
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
- **Numbering is at least two digits:** 01, 02, ..., 10, 11, ..., 497, 498...
- **TNN: scan recursively including Done/.** The maximum number across all files — not only active tasks.
- **SNN: scan `{docs.specifications}` recursively, including its backlog subdirectory if present.**
- If the type is not specified — ask first, do not guess.
- If content clarifications are needed — ask **one question** at a time.
- If a file with that number already exists — report it and ask what to do.
- The date in the document is always today (`currentDate` from the system context).
