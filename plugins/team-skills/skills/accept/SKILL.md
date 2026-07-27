---
name: accept
description: >
  Closes the current task: marks it as done in the task file, the specification,
  and HANDOFF.md, adds an entry to CHANGELOG.md, and moves the file into the Done folder.
  Use when the user says "/accept", "/accept T07", "закрой задачу",
  "таска выполнена", "помечай как done", "принять задачу".
---

# Accept Skill

Documents the completion of a task. Documentation only — no DoD verification (the user does that).
No questions — do everything in a single pass.

---

## Inputs

- `/accept` — the task is detected automatically from `*HANDOFF.md` (the first one with status 🟡)
- `/accept T07` — explicit task number

---

## Algorithm

### Step 1 — Determine the task

**If the number is passed explicitly** (e.g. `T07`):
- Find the file: `glob docs/3. *tasks/T07_*.md`

**If no number is passed**:
- Read `*HANDOFF.md` (adapt to the project prefix: SUP-, CLB-, ARP-, etc.)
- Find the first task with status 🟡 in any table
- Use it — no clarification

### Step 2 — Read the task file

Read the task file. Extract:
- **Task title** (from the heading `# TNN_...` or `**Задача:**`)
- **Specification** (from the line `**Спецификация:** docs/2. *specifications/SNN_*.md`)
- **SNN** — the spec number (e.g. `S02`)
- **Spec name** in snake_case (e.g. `hypothesis_prototyping`)

### Step 3 — Determine the Done path

```
Done-папка:  docs/3. SUP-tasks/Done/SNN_<spec_name>_done/
Новый файл:  docs/3. SUP-tasks/Done/SNN_<spec_name>_done/TNN_<task_name>_done.md
```

If the Done folder does not exist — create it.

### Step 4 — Update the task file

Add to the top of the task file (after the `# ...` heading):

```markdown
**Статус:** ✅ Выполнено
**Дата закрытия:** YYYY-MM-DD
```

### Step 5 — Move the task file

1. Write the updated content to the new path: `Done/SNN_<spec_name>_done/TNN_<task_name>_done.md`
2. Delete the source file: `docs/3. SUP-tasks/TNN_<task_name>.md`
3. If the source task folder has become empty — delete it

### Step 6 — Update the specification

Read the specification file from the `**Спецификация:**` line of the task.

Find the table row with this TNN. Replace the status in the last column with `✅ YYYY-MM-DD`.

Example:
```
| T07 | Инфраструктура... | Костя | 🟡 в работе |
→
| T07 | Инфраструктура... | Костя | ✅ 2026-03-24 |
```

**If all tasks of the specification now have status ✅** — add the suffix `_done` to the spec file name:
```
docs/2. SUP-specifications/S02_hypothesis_prototyping.md
→ docs/2. SUP-specifications/S02_hypothesis_prototyping_done.md
```

### Step 7 — Update HANDOFF.md

Find the row with this TNN in any table of `*HANDOFF.md`. Replace the status with `✅ YYYY-MM-DD`.

If the task was the current blocker — remove or update the `**Текущий блокер TNN:**` line.

**If ALL tasks of the phase/block are done** — compactify the block: collapse the detailed task table into a single summary row.

### Step 8 — Update CHANGELOG.md

In the `## [Не выпущено]` → `### Added` section, add a line:

```markdown
- YYYY-MM-DD — TNN: <краткое описание что сделано>
```

The short description is the first 1–2 sentences from the task description.

### Step 9 — Update references

Search for the old task path across all `.md` files:
```
grep -r "docs/3. SUP-tasks/TNN_<task_name>.md"
```

For each file found — replace the old path with the new one:
```
docs/3. SUP-tasks/Done/SNN_<spec_name>_done/TNN_<task_name>_done.md
```

If the spec was renamed in step 6 — likewise update all references to it.

### Step 10 — Report

Output a summary:

```
✅ Задача T07 закрыта (2026-03-24)

Файл перенесён:
  docs/3. SUP-tasks/T07_s02_test_instance_setup.md
  → docs/3. SUP-tasks/Done/S02_hypothesis_prototyping_done/T07_s02_test_instance_setup_done.md

Обновлено:
  ✅ docs/2. SUP-specifications/S02_hypothesis_prototyping.md — статус T07
  ✅ *HANDOFF.md — статус T07
  ✅ *CHANGELOG.md — добавлена запись

Ссылки обновлены в: N файлах
```

If the spec was renamed or HANDOFF was compactified — add a separate line to the report.

---

## Rules

- The closing date is always today (`currentDate` from the system context)
- Never delete a task without an entry in CHANGELOG
- If the task file is not found — report an error, do not proceed
- If the Done folder for this spec already exists — just use it
- Adapt to the project prefixes (SUP-, CLB-, ARP-, etc.) — take them from HANDOFF/task files
