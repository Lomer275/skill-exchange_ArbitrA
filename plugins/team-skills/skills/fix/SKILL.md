---
name: fix
description: >
  Planning and applying bug fixes from a code review or a visual check.
  Use this skill when the user asks to fix bugs, apply fixes from a review,
  says "/fix", "исправь баги", "применяй фиксы", "fix bugs",
  "почини", "fix T01", or when fixes need to be applied after /codereview or
  /visualcheck. The skill first builds a fix plan and waits for confirmation,
  then makes minimal, targeted changes and verifies the result.
---

# Fix Skill

Planning and applying fixes from a code review (CRITICAL → HIGH → MEDIUM).
Minimal, targeted changes. Does not start without confirmation.

---

## Inputs

The user provides one or more of:
- **A findings table** from `/codereview` or `/visualcheck` (pasted into chat)
- **A task file** with a `## Code Review` section
- **A specific bug** to fix (described in words)
- **The code of files** to fix

If there is no findings table — ask to run `/codereview` first.

---

## Execution algorithm

### Step 1 — Gather context

1. Find and read the **findings table** (from the review or from the user)
2. Read the **source code** of the affected files (the user must provide it)
3. Filter the bugs by severity: CRITICAL → HIGH → MEDIUM, skip those already marked FIXED
4. If the bugs are UI/* from visualcheck — clarify which of them need fixing

---

### Step 2 — Build a plan (MANDATORY before any changes)

For each bug, build a plan:

```
## План фиксов

### R1 — CRITICAL — [Краткое название]
**Root cause:** Почему это происходит (конкретно)
**Файл:** path/to/file.ts
**Изменение:** Что именно меняем (строки N–M)
**Минимальный фикс:** [одна строка или минимальный блок]
**Риск:** Низкий / Средний / Высокий — почему

### R2 — HIGH — [Краткое название]
...

**Итого:** N фиксов, затронуто M файлов
```

After the plan — **stop and wait for the user's confirmation**.

Trigger phrases to continue: "делай", "go", "применяй", "ок", "давай", "+".

---

### Step 3 — Apply the fixes (executable code → delegate to Codex)

After confirmation. **Division of labour (S11): the plan above is Claude's; typing the code is Codex's.**
The plan you just wrote *is* the brief — it already has root cause, file, exact change and risk.

1. **Executable code** (`*.py`, `tests/`, `*.sql`, `*.sh`, `*.js`) → delegate:
   - `Write` the confirmed plan to `/tmp/sup-codex/fix-<slug>-brief.md` (add a `# ГРАНИЦЫ` section listing exactly the files from the plan, and `# DoD` = the finding no longer reproduces + existing tests stay green).
   - `Skill(skill="codex-worker", args="role=implementer brief_file=/tmp/sup-codex/fix-<slug>-brief.md scope=edit:<файлы из плана> task_id=fix-<slug> timeout_min=15")`
   - Findings touching **disjoint** files may go to N workers in parallel; overlapping files → strictly sequential.
   - Then **read `git diff` yourself** and check each fix against its plan entry. Deviation → one corrective round; second miss on the same finding → finish it yourself and say so.
   - Codex unavailable / kill-switch off → announce one line and apply the fixes directly. `/fix` never blocks on Codex.
2. **Docs, specs, configs, task files** → Claude edits directly, no delegation.
3. **Fix one bug at a time** — one bug = one minimal change
4. **Do not refactor along the way** — only what is in the plan
5. **Show the changes** as a diff or "before / after":

```
### Фикс R1 — [Название]

**Было:**
```ts
// проблемный код
const result = query + userInput; // SQL injection
```

**Стало:**
```ts
// фикс
const result = db.query('SELECT * WHERE id = ?', [userInput]);
```
```

6. After each file — report what was changed, and say who wrote it (Codex / Claude-fallback)

---

### Step 4 — Verification

After applying all the fixes:

**Ask the user** to check:
- Run the application / tests
- Walk through the scenario that reproduced the bug
- For UI fixes — take a screenshot and upload it

**If the user reported an error** — analyze it, propose a corrected fix. Up to 5 iterations. If it did not work — honestly write `❌ НЕ УДАЛОСЬ починить за 5 попыток` with a description of what was tried.

---

### Step 5 — Summary

```
## Результат фиксов

| ID | Severity | Статус | Комментарий |
|----|----------|--------|-------------|
| R1 | CRITICAL | ✅ FIXED | Параметризованный запрос в api/users.ts:34 |
| R2 | HIGH | ✅ FIXED | clearToken() добавлен в logout() |
| R3 | MEDIUM | ⚠️ PARTIAL | Обработан undefined, но не null — нужен доп. фикс |
| R4 | LOW | ⏭️ SKIP | Пропущен по договорённости |

**Итого:** 2 FIXED, 1 PARTIAL, 1 SKIP
**Рекомендация:** Запустить /codereview повторно для верификации
```

---

## Rules

- **Do not start without confirmation** — plan first, then wait for "делай"
- **Minimal fix** — do not refactor, do not rewrite, do not improve along the way
- **One bug = one change** — do not mix several fixes into one block
- **If a file was not provided** — ask for it before proposing a fix
- **Order**: CRITICAL → HIGH → MEDIUM, LOW — by agreement with the user
- **Do not guess the context** — if it is unclear how a module is built, ask to see the related code
- **Honesty on timeout**: if it did not work within 5 iterations — admit it, do not invent a workaround without warning

---

## Fast mode

If the user says "фикси всё без остановки" / "go straight" — you may skip waiting for confirmation and apply the plan right away. But still show the plan before the fixes.
