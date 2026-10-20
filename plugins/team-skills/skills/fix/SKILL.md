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
3. Filter the bugs by severity: CRITICAL → HIGH → MEDIUM, skip those already marked FIXED. Skip `OLD-` rows — older bugs on main, outside the change — unless the user names them by ID
4. If the bugs are UI/* from visualcheck — clarify which of them need fixing
5. **Check which tree you are fixing** — `/codereview` Step 0: read it and run its commands from the repo root. Findings that step did not sort — a pasted table, a bug described in words, a review with no «Дерево» line — sort now, the rows left after item 3, by its cases. A phantom → no fix: `rejected` (Step 5b), the logged summary starting «фантом устаревшего дерева:». An `OLD-` row the user did name → plan it for a worktree next to the repo, off main: `git worktree add ../<repo>-wt/fix-<slug> -b fix/<slug> origin/main`, then `worktree=<that path>` for codex-worker; every git and pytest command of Steps 3–4 for that row runs there. A tree behind main, or with dirty entries outside the change (`/codereview` Step 0 defines both) → the «Дерево» line goes under the plan heading and under the Step 5 table: the user decides where the fixes go

---

### Step 2 — Build a plan (MANDATORY before any changes)

For each bug, build a plan:

```
## План фиксов
Дерево: <ветка>, позади main: N, впереди: M, грязных вне изменения: K — фиксы идут в <эту ветку | ../<repo>-wt/fix-<slug>>   ← только если Шаг 1 п. 5 это требует

### R1 — CRITICAL — [Краткое название]
**Root cause:** Почему это происходит (конкретно)
**Файл:** path/to/file.ts
**Изменение:** Что именно меняем (строки N–M)
**Минимальный фикс:** [одна строка или минимальный блок]
**Тест:** tests/…/test_x.py::test_… — дано …; когда …; тогда …; красный: <как падает на нынешнем коде — исключение или расхождение и продовый кадр> (или «без теста: <причина из списка Шага 3>; проверка: …»)
**Риск:** Низкий / Средний / Высокий — почему

### R2 — HIGH — [Краткое название]
...

**Итого:** N фиксов, затронуто M файлов (из них тестовых: T)
```

«Тест» is the finding's **воспроизводящий тест**: it walks the code path from the failure scenario and fails until the fix lands. One per finding of executable code. **Red** means it fails with the exception or assertion that «красный» predicts, raised through the named production frame. An error in the test's own code (`NameError`, a wrong signature, a missing fixture) is not red. A пример-страховка is expected green on both passes.

After the plan — **stop and wait for the user's confirmation**.

Trigger phrases to continue: "делай", "go", "применяй", "ок", "давай", "+".

---

### Step 3 — Apply the fixes (executable code → delegate to Codex)

After confirmation. **Division of labour (S11): the plan above is Claude's; typing the code is Codex's.**
The plan you just wrote *is* the brief — it already has root cause, file, exact change and risk.

1. **Executable code** (`*.py`, `tests/`, `*.sql`, `*.sh`, `*.js`) → delegate, in two passes, so that you see every воспроизводящий тест fail before the fix exists:
   - `Write` the confirmed plan as a brief to `~/sup-codex/fix-<slug>-brief.md` (not `/tmp`: some hosts wipe it nightly). `codex-worker` rejects a brief with an empty required section, so the brief carries all eleven sections of the `/impl` template; for a fix they map almost one-to-one onto the plan:
     - `ЗАДАЧА` — «починить находки R…»; `КОНТЕКСТ` — root cause of each finding; `ЧТО СДЕЛАТЬ` — the plan entries;
     - `ГРАНИЦЫ` — «правь только файлы из ФАЙЛЫ»; `ФАЙЛЫ` — exactly the files from the plan, the test files included, one per bullet;
     - `ПРИМЕРЫ` — per finding, its воспроизводящий тест: the **failure scenario** rewritten as «Дано …; когда …; тогда <верное поведение>», calling the code path from the scenario, not a new helper directly. At least two examples: a single finding → add a **пример-страховка** «существующее поведение X не меняется»;
     - `КРАЙНИЕ СЛУЧАИ`, `ПЕРЕИСПОЛЬЗОВАТЬ`, `ВНЕ СКОУПА` (the other findings, refactoring), `БЮДЖЕТ` (usually `час`);
     - `DoD` — pass 1: only the tests from `ПРИМЕРЫ`, production code untouched; pass 2: every воспроизводящий тест is green, the scenario no longer reproduces, existing tests stay green, the test files are not edited. A finding that no test can reproduce (the list below) → the DoD says so and names the check that replaces the test.
   - `python3 scripts/staff/brief.py check ~/sup-codex/fix-<slug>-brief.md` → exit 0 before delegating (absent script → say so in one line and check by eye).
   - **Snapshots.** The tree is often dirty with other work, so `git status` and `git diff` cannot tell the worker's lines from someone else's. Take the `/impl` Step 3 snapshot (same command and cautions, names `fix-<slug>`) three times: `-before1.tree` before pass 1, `-after1.tree` after it, `-after2.tree` after pass 2. Below, `<before1>`, `<after1>`, `<after2>` are those tree ids; with a single pass, `<after1>` is `<before1>`.
   - **Pass 1 — tests.** Append «Проход 1 из 2: только тесты из ПРИМЕРЫ, продовый код не трогай» to the brief, then `Skill(skill="codex-worker", args="role=implementer brief_file=$HOME/sup-codex/fix-<slug>-brief.md scope=edit:<тестовые файлы из ФАЙЛЫ> task_id=fix-<slug>-tests timeout_min=15")`. Only findings with a test take part; when none has one, there is no pass 1 (see «No test possible»).
   - **Red run — yours, not the worker's.** `git -C <repo> diff-tree -r --name-status <before1> <after1>` lists only test files from ФАЙЛЫ. Run the new tests (Step 4 says how) and keep the tail. Each воспроизводящий тест must be red as Step 2 defines it. What is not red:
     - an error before the test reaches the code — DB connection refused, `DuplicateDatabase`, an import the host's older Python lacks, a required env var not set at collection — is the environment: fix the run (`/impl` Step 4 item 4), do not send the worker back. The DB stays unreachable → that finding goes on as «без теста: БД недоступна»;
     - an error in the test's own code, or a SKIPPED / XFAIL result → send it back;
     - the test passes on the unfixed code → send it back once, with the scenario's code path spelled out. Passes again → walk the scenario yourself. It does not reproduce → `rejected` «сценарий не воспроизводится» (Step 5b), and pass 2's brief says «удали тест <имя>: он не воспроизводит находку». It does reproduce → the worker missed twice: write the test yourself (pocket, announce it).
   - **Pass 2 — the fix.** Delete the «Проход 1 из 2…» line from the brief, append `# КРАСНЫЙ ПРОГОН` with the tails in a code block and «Проход 2 из 2: почини, тесты не меняй», then the same call with `scope=edit:<остальные файлы из ФАЙЛЫ> task_id=fix-<slug>`. `git -C <repo> diff-tree -r --name-status <after1> <after2>` must not list the test files, except a `D` of a test the brief told the worker to delete (that file goes into this pass's `scope=edit` too); any other test-file change → send the worker back with its own hunks — never `git checkout` a file, it may hold other people's work. Run the same tests again → green, plus the existing tests of the touched modules.
   - A pass that ends `status: timeout|error` → read `/tmp/sup-codex/<task_id>-implementer.err`, retry once with a longer `timeout_min`, then take over.
   - Findings touching **disjoint** files may go to N workers in parallel; overlapping files → strictly sequential.
   - Then **read the diff yourself** — `git -C <repo> diff <before1> <after2>`: new files are in it, earlier dirt is not — and check each fix against its plan entry. Deviation → one corrective round: the same brief plus `# ПРАВКИ ПО РЕВЬЮ` saying what is wrong, re-delegated once. Second miss on the same finding → finish it yourself in the same order (test, red run, fix, green run) and say so; more than 3 lines typed by you in total → a fresh reviewer before the report, as in `/impl` Step 4 item 6.
   - **No fake completion.** In the added lines (a new file counts in full), unless the plan asked for it: `pytest.skip` / `@pytest.mark.skip` / `skipif` / `xfail`, `raise NotImplementedError`, a body of only `pass` or `...` next to a TODO, `assert True` or a test with no real assertion → that finding is not fixed: quote the line in `# ПРАВКИ ПО РЕВЬЮ`. An empty diff is not `ok` either — unless the worker explains why the finding is not real and you have checked it: then the finding is `rejected`, not a blocker. Nothing automatic catches these: `/fix` runs no scope gate.
   - **No test possible** — only for: a prompt or DB text, config or env, a UI-only change, a live external service or prod data, timing or a race, a file type with no test runner on main (`*.sh` without a pytest wrapper, `*.sql`, `*.js`), a DB unreachable for the run. You decide that, not the worker; the brief names the check that replaces the test (a manual scenario, a log line, a screenshot), and the Step 5 row is ⚠️ PARTIAL «исправлено без воспроизведения». When no finding of the run has a test, there is one pass: no «Проход» lines, no `# КРАСНЫЙ ПРОГОН`, and `ПРИМЕРЫ` holds the manual scenarios in дано/когда/тогда form (the checker wants at least two). Never pass off a test that never failed as the воспроизводящий тест.
   - Codex unavailable / kill-switch off → announce one line and apply the fixes directly, in the same order: test, red run, fix, green run, with the same snapshots around your own edits; more than 3 lines typed by you in total → a fresh reviewer, `/impl` Step 4 item 6. `/fix` never blocks on Codex.
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

After applying all the fixes, run the tests yourself: the red runs of Step 3 and a final green run of the воспроизводящие тесты plus the existing tests of the touched modules. Use the command and environment of `/impl` Step 4 item 4, with `--tb=short` added so the red tails stay short; a run for an `OLD-` row goes in its worktree. Show the tail of each run. `django_db` tests need a database: a run that cannot connect proves nothing either way — say so instead of reporting green.

**Ask the user** only for what you cannot do:
- Walk through the scenario that reproduced the bug in the live bot
- For UI fixes — take a screenshot and upload it

**If the user reported an error** — analyze it, propose a corrected fix. Up to 5 iterations. If it did not work — honestly write `❌ НЕ УДАЛОСЬ починить за 5 попыток` with a description of what was tried.

---

### Step 5 — Summary

```
## Результат фиксов

| ID | Severity | Статус | Исход | Комментарий |
|----|----------|--------|-------|-------------|
| R1 | CRITICAL | ✅ FIXED | accepted | Параметризованный запрос в api/users.ts:34 |
| R2 | HIGH | ✅ FIXED | accepted | clearToken() добавлен в logout() |
| R3 | MEDIUM | ⚠️ PARTIAL | accepted | Обработан undefined, но не null — нужен доп. фикс |
| R4 | MEDIUM | ⚠️ PARTIAL | accepted | Исправлено без воспроизведения: текст промпта; проверено вручную на тестовых данных |
| R5 | MEDIUM | ❌ REJECTED | rejected | Фантом устаревшего дерева: на main функция уже проверяет None |
| R6 | LOW | ⏭️ SKIP | — | Пропущен по договорённости |

**Итого:** 2 FIXED, 2 PARTIAL (из них без воспроизведения: 1), 1 REJECTED, 1 SKIP
**Рекомендация:** Запустить /codereview повторно для верификации
```

Under the table, for every ✅ FIXED row of executable code: the воспроизводящий тест and the tail of its red run on the unfixed code (test name + the failing assertion), from Step 3. A fixed finding of executable code without a red run is ⚠️ PARTIAL «исправлено без воспроизведения» with its reason from the Step 3 list — never ✅ FIXED. A doc or config fix Claude made directly (Step 3 item 2) needs no red run. If the plan carried a «Дерево» line, repeat it under the table.

### Step 5b — Finding outcomes to the metrics log

Each resolved finding gets an outcome, and the outcome goes to `~/sup-staff/metrics.jsonl`. The point is to learn, over weeks, which reviewer brings findings that survive — so the outcome is about the **finding**, not about effort:

| Fix status | Outcome |
|---|---|
| ✅ FIXED, ⚠️ PARTIAL — the finding was real and this diff addresses it | `accepted` |
| ❌ rejected — false positive, a phantom of a stale tree, the scenario does not reproduce, contradicts the task; **reason goes in the Комментарий column** | `rejected` |
| ⏭️ SKIP by agreement (real, deferred) | not logged now — logged by the `/fix` run that finally resolves it |

For every `accepted` / `rejected` row:

```bash
python3 scripts/staff/metrics.py log --task <KEY> --event review_finding_outcome \
  --value '{"source":"claude|codex|both","severity":"HIGH","file":"path/x.py","line":42,"summary":"<одна строка>","outcome":"accepted"}'
```

- `source` — from the review table's «Источник» column: `[both…]` → `both`, `[claude]` → `claude`, `[codex]` → `codex`; a finding the user reported in words → `claude`.
- `<KEY>` — the tracker's task number if there is one, else the TNN (`T12`), else `impl-<slug>` for an ad-hoc `/impl` change.
- `summary` of a phantom starts with «фантом устаревшего дерева:» — so the log can tell a wrong finding from a stale tree.
- `scripts/staff/metrics.py` absent in this checkout → put the outcomes in the summary table anyway and add one line: «журнал метрик пропущен: metrics.py нет в рабочей копии».

---

## Rules

- **Do not start without confirmation** — plan first, then wait for "делай"
- **Minimal fix** — do not refactor, do not rewrite, do not improve along the way
- **One bug = one change** — do not mix several fixes into one block
- **Red before green** — every fix of executable code has a воспроизводящий тест you saw fail on the unfixed code (Step 3), or a reason from the closed list and a ⚠️ PARTIAL row
- **If a file was not provided** — ask for it before proposing a fix
- **Order**: CRITICAL → HIGH → MEDIUM, LOW — by agreement with the user
- **Do not guess the context** — if it is unclear how a module is built, ask to see the related code
- **Honesty on timeout**: if it did not work within 5 iterations — admit it, do not invent a workaround without warning

---

## Fast mode

If the user says "фикси всё без остановки" / "go straight", or the args carry `--fast` (the review loops pass it) — you may skip waiting for confirmation and apply the plan right away. But still show the plan before the fixes. `--severity=<list>` (e.g. `CRITICAL,HIGH`) limits the plan to those severities.

`OLD-` rows stay out of it unless the user names them. Every other kept finding is fixed in this tree, «есть только в ветке» and «не проверено на main» included, and its mark goes into the Комментарий of its Step 5 row. This matches what the loops count: a kept row that fast mode left alone would never stop counting.
