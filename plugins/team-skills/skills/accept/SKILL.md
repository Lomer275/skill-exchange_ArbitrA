---
name: accept
description: >
  Closes the current task: marks it as done in the task file, the specification,
  and HANDOFF.md, adds an entry to CHANGELOG.md, and moves the file into the Done folder.
  Use when the user says "/accept", "/accept T07", "закрой задачу",
  "таска выполнена", "помечай как done", "принять задачу".
  If the project or the user has its own `accept` skill, that one takes precedence — use this one only when the user typed `/team-skills:accept` or no such skill exists.
---

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:accept` and a skill named `accept` exists in the project (`.claude/skills/accept/SKILL.md`) or in the user's skills (`~/.claude/skills/accept/SKILL.md`), stop: tell the user that their own `/accept` takes precedence, and do nothing else.

## Project profile (mandatory)

After Step 0 and before any other action, read `.claude/team-skills.json` from the repository root. Require format `version: 1` and these keys: `handoff`, `changelog`, `docs.tasks`, `docs.tasks_done`, `docs.specifications`. Read only the keys needed for this invocation. A missing file, unsupported version, or missing/empty required key means stop before reading or changing project documents: name the missing file/key and point to `team-skills:init_dev` and the catalog's `docs/team-skills-profile.md`. Never infer a prefix or substitute project paths.

In this skill, `{key}` means the value of that profile key; resolve paths relative to the repository root. These are notation, not literal shell variables: substitute and shell-quote the resolved values before executing commands. Paths must stay inside the repository.

# Accept Skill

Documents the completion of a task. Documentation only — no DoD verification (the user does that).
After the mandatory checks, complete the documented task closure in a single pass. This skill does not commit or push.

---

## Inputs

- `/accept` — the task is detected automatically from `{handoff}` (the first one with status 🟡)
- `/accept T07` — explicit task number

---

## Algorithm

### Step 1 — Determine the task

**If the number is passed explicitly** (e.g. `T07`):
- Find the file: `glob {docs.tasks}/T07_*.md`

**If no number is passed**:
- Read `{handoff}`
- Find the first task with status 🟡 in any table
- Use it — no clarification

### Step 2 — Read the task file

Read the task file. Extract:
- **Task title** (from the heading `# TNN_...` or `**Задача:**`)
- **Specification** (from the line `**Спецификация:** {docs.specifications}/SNN_*.md`)
- **SNN** — the spec number (e.g. `S02`)
- **Spec name** in snake_case (e.g. `hypothesis_prototyping`)

### Step 3 — Determine the Done path

```
Done-папка:  {docs.tasks_done}/SNN_<spec_name>_done/
Новый файл:  {docs.tasks_done}/SNN_<spec_name>_done/TNN_<task_name>_done.md
```

If the Done folder does not exist — create it.

### Step 4 — Update the task file

If the task file starts with YAML frontmatter, it is the source of truth for the status: set `status: done` and add `completed: YYYY-MM-DD`; do not add a status line under the heading. Without frontmatter — add to the top of the task file (after the `# ...` heading):

```markdown
**Статус:** ✅ Выполнено
**Дата закрытия:** YYYY-MM-DD
```

### Step 5 — Move the task file

1. Write the updated content to the new path: `{docs.tasks_done}/SNN_<spec_name>_done/TNN_<task_name>_done.md`
2. Delete the source file: `{docs.tasks}/TNN_<task_name>.md`
3. If the source task folder has become empty — delete it

### Step 6 — Update the specification

Read the specification file from the `**Спецификация:**` line of the task.

Find the table row with this TNN. Replace the status in the last column with `✅ YYYY-MM-DD`.

Example:
```
| T07 | Инфраструктура... | the project owner | 🟡 в работе |
→
| T07 | Инфраструктура... | the project owner | ✅ 2026-03-24 |
```

**If all tasks of the specification now have status ✅** — add the suffix `_done` to the spec file name:
```
{docs.specifications}/S02_hypothesis_prototyping.md
→ {docs.specifications}/S02_hypothesis_prototyping_done.md
```

### Step 7 — Update `{handoff}`

Find the row with this TNN in any table of `{handoff}`. Replace the status with `✅ YYYY-MM-DD`.

If the task was the current blocker — remove or update the `**Текущий блокер TNN:**` line.

**If ALL tasks of the phase/block are done** — compactify the block: collapse the detailed task table into a single summary row.

### Step 8 — Update `{changelog}`

Under `## [Не выпущено]`, add a line to the subsection the project uses: when subsections are per initiative (`### Added (<тема>, YYYY-MM-DD)` / `### Fixed (…)`) — to this task's one, creating it at the top if there is none; otherwise to `### Added`:

```markdown
- YYYY-MM-DD — TNN: <краткое описание что сделано>
```

The short description is the first 1–2 sentences from the task description.

### Step 9 — Update references

Search for the old task path across all `.md` files:
```
rg -n --fixed-strings "{docs.tasks}/TNN_<task_name>.md"
```

For each file found — replace the old path with the new one:
```
{docs.tasks_done}/SNN_<spec_name>_done/TNN_<task_name>_done.md
```

If the spec was renamed in step 6 — likewise update all references to it.

### Step 10 — Report

Output a summary:

```
✅ Задача T07 закрыта (2026-03-24)

Файл перенесён:
  {docs.tasks}/T07_s02_test_instance_setup.md
  → {docs.tasks_done}/S02_hypothesis_prototyping_done/T07_s02_test_instance_setup_done.md

Обновлено:
  ✅ {docs.specifications}/S02_hypothesis_prototyping.md — статус T07
  ✅ {handoff} — статус T07
  ✅ {changelog} — добавлена запись

Ссылки обновлены в: N файлах
```

If the spec was renamed or HANDOFF was compactified — add a separate line to the report.

---

## Rules

- The closing date is always today (`currentDate` from the system context)
- Never delete a task without an entry in CHANGELOG
- If the task file is not found — report an error, do not proceed
- If the Done folder for this spec already exists — just use it
- All project paths come from the profile; never discover them from filename prefixes.
