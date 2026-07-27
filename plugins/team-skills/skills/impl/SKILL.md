---
name: impl
description: >
  Delegates writing code to a Codex implementer for ANY change — no TNN task file
  required. Claude does the thinking (locates the code, decides the approach, writes
  a precise brief), Codex writes the code, Claude reviews the resulting diff and runs
  the tests. This is the DEFAULT path for any code change in SUP: Claude decides,
  Codex implements. Use when the user says "/impl", "реализуй", "напиши код",
  "сделай правку", "поправь", "внеси изменение", "добавь фичу", "перепиши",
  or whenever a change to executable code (*.py, tests/, *.sql, *.sh, *.js) is needed
  outside of /sprint-codex (which is spec-driven) and /fix (which consumes review findings).
  Part of spec S11 — the Claude × Codex division of labour.
---

# /impl — Claude decides, Codex implements

The generic delegation path. `/sprint-codex` covers spec-driven waves, `/fix` covers
review findings — **`/impl` covers everything else**: an ad-hoc change, a new function,
a refactor, a bug fix found in conversation.

**The division of labour is the whole point.** Claude must not hand Codex a raw user
sentence and call it delegation — that produces a worker that guesses the design.
Claude does the thinking; Codex only types.

| Stage | Owner | Output |
|---|---|---|
| Understand the request, locate the code, pick the approach | **Claude** | a brief |
| Write the code | **Codex** | a diff |
| Review the diff, run the tests, decide "good / redo" | **Claude** | a verdict |

---

## Input

- `/impl <что нужно сделать>` — free-form description.
- `/impl` with no argument → use the task from the current conversation. If unclear, ask **one** clarifying question.
- `--files a.py,b.py` — optional explicit scope override (otherwise Claude derives it in Step 1).
- `--self` — an explicit user override: Claude implements it directly (skips delegation). Announce and proceed as a normal edit.

---

## Algorithm

### Step 0 — Routing checks

1. **Kill-switch.** Read `.claude/codex.json:enabled` + env `SUP_CODEX_ENABLED` (precedence matrix: recognized env value wins, else file — see [runbook_codex_routing.md](../../../docs/4.%20SUP-guides/runbook_codex_routing.md)).
2. **Availability.** `availability_cache` fresh (≤ 1h) → use it; otherwise re-check the binary + a smoke run.
3. **CLI version** ≥ 0.143.0 (`codex --version`) — older CLIs race the OAuth refresh under parallel workers.

**If Codex is disabled or unavailable → do NOT stop.** Announce one line —
«Codex недоступен (<причина>) — реализую сам, это карман исключений» — and implement
the change with `Edit`/`Write` yourself. `/impl` degrades to normal work rather than blocking.

---

### Step 1 — Claude thinks (mandatory, do not skip)

This is the step that makes the delegation worth anything. Before writing the brief:

1. **Locate the code.** `Grep`/`Glob`/`Read` the relevant files. Never delegate against a guessed path.
2. **Understand the surroundings.** Read the module's `CLAUDE.md` (`max_bot/`, `tg_bot/`, `Handler/`, `bitrix/`, `shared/`) — it holds the module's patterns and pitfalls.
3. **Decide the approach.** Where the change goes, which existing helper to reuse, what must NOT be touched, what the edge cases are. If two approaches are genuinely open and the choice is the user's, ask *before* delegating — never hand ambiguity to Codex.
4. **Fix the scope.** The exact list of files Codex may edit. This becomes `scope=edit:<paths>`.
5. **Define the DoD.** How we will know it works: which test, which command, which observable behaviour.

If Step 1 reveals the change is a one-liner in a file already open in this session
(≤ 3 lines, obvious, zero design content) → this is the exceptions pocket:
announce «Делаю сам — правка N строк, брифовать дороже» and edit directly. Skip to Step 4.

---

### Step 2 — Write the brief

`Write` it to `/tmp/sup-codex/impl-<slug>-brief.md`, where `<slug>` is a short kebab-case
name of the change (e.g. `voice-rate-limit`). Template:

```markdown
# ЗАДАЧА
<одно предложение: что должно измениться в поведении системы>

# КОНТЕКСТ
<почему; какой баг/фича; что уже выяснил Claude — путь, виновная строка, механизм>
Модуль: <max_bot|tg_bot|Handler|bitrix|shared|...> — читай его CLAUDE.md.

# ЧТО СДЕЛАТЬ
1. <шаг с указанием файла и функции>
2. <...>

# ГРАНИЦЫ
Правь ТОЛЬКО: <file1.py, file2.py, tests/...>
НЕ трогай: <всё остальное; рефакторинг вне задачи; переименования>

# КРАЙНИЕ СЛУЧАИ
- <что должно произойти при пустом значении / ошибке сети / выключенном флаге>

# DoD
- <проверяемый критерий: тест X зелёный / команда Y печатает Z>
- Существующие тесты не сломаны.
```

**Quality bar for the brief:** a competent engineer who has never seen this
conversation must be able to implement it without asking a question. If your brief
fails that bar, you skipped Step 1.

---

### Step 3 — Delegate

Call the worker via the Skill tool:

```
Skill(skill="codex-worker", args="role=implementer brief_file=/tmp/sup-codex/impl-<slug>-brief.md scope=edit:<paths> task_id=impl-<slug> timeout_min=15")
```

- `worktree` — omit (defaults to `current`). Pass a worktree path only when the caller is already isolated.
- **Parallel changes.** If Step 1 decomposed the request into ≥2 changes with **no shared files**, write one brief each and call `codex-worker` N times in a single message. Overlapping files → sequential, no exceptions (concurrent workers on one file clobber each other).

Announce the delegation in one line: «Отдаю Codex: <что>. Скоуп: <файлы>».

---

### Step 4 — Claude reviews (mandatory)

Codex returning `status: ok` is not evidence the change is right.

1. **Read the diff:** `git diff -- <scope files>` — actually read it, not just the worker's summary.
2. **Check against the brief:** does it do what was asked, and *only* that? Flag scope creep (untouched-file edits, drive-by renames, gratuitous refactoring).
3. **Check the pitfalls** the module's `CLAUDE.md` warns about.
4. **Run the tests:**
   ```bash
   DATABASE_URL=... python -m pytest tests/unit/<relevant> -q
   ```
   (dev needs `DATABASE_URL` — `test_settings` expects `localhost:5432`; in-container it is `db:5432`.)
5. **Verdict:**
   - Clean → Step 5.
   - Small deviation → **one** corrective round: append a `# ПРАВКИ ПО РЕВЬЮ` section to the brief and re-delegate (Step 3).
   - **Second failure on the same change** → exceptions pocket: Claude finishes it directly, announcing «Codex дважды промахнулся — доделываю сам». Do not loop.
   - Worker `status: timeout|error` → read `/tmp/sup-codex/<task_id>-implementer.err`, one retry with a longer timeout, then take over.

---

### Step 5 — Report

One screen:

- **Что изменено** — files with line counts, one line of intent each.
- **Тесты** — the command and its actual result (paste the tail; never claim green without output).
- **Риски / follow-ups** — anything the change leaves open.
- **Не закоммичено** — state it plainly.

**Never commit or push.** Commits happen only on the user's explicit request (`/sup-push`).

---

## Rules

- **Claude does not write executable code by default.** `*.py`, `tests/`, `*.sql`, `*.sh`, `*.js` are Codex's. Docs (`*.md`), specs, task files, configs (`*.yml`, compose, workflows) and agent memory stay with Claude — that is the "thinks and decides" half.
- **The exceptions pocket is narrow and must be announced out loud:** Codex unavailable · ≤3-line obvious edit in an already-open file · second Codex miss on the same change · the change requires live dialogue with the user mid-edit · `--self`.
- **Never delegate a brief you could not implement yourself.** If you cannot specify it, you have not understood it — go back to Step 1.
- **Never trust `touchedFiles`** from the companion engine — determine the changed files via `git`.
- Codex does not commit, does not touch `.env*`, `SUP-CHANGELOG.md`, `SUP-HANDOFF.md` or `docs/3. SUP-tasks/Done/` — enforced by `AGENTS.md`, restated in the brief when the scope is near them.

---

## Related

- [runbook_codex_routing.md](../../../docs/4.%20SUP-guides/runbook_codex_routing.md) — the routing matrix and the division-of-labour law.
- `/sprint-codex` — the same delegation, but spec-driven with waves and worktrees.
- `/fix` — applies findings from `/codereview*` (delegates to Codex the same way).
- `/codereview-dual` — Codex as reviewer, not implementer.
