---
name: sprint
description: "Autonomous orchestrator for executing a specification. Reads all 🟡 tasks from the spec, groups them into waves by dependencies, and runs each wave in parallel. Supports a headless `/sprint --yes <Sxx>` mode: at each checkpoint it consults `scripts/autopilot/check_authz.py` (which reads the ```yaml autopilot``` block from the profile handoff file) and decides auto-go vs TG-ask-and-wait instead of waiting on stdin. Use when the user says '/sprint S02', 'прогони спринт', 'выполни спеку', '/sprint --yes S14', 'запусти спринт в cron-режиме', 'автономный спринт'. If the project or the user has its own `sprint` skill, that one takes precedence — use this one only when the user typed `/team-skills:sprint` or no such skill exists."
---

# Sprint Skill

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:sprint` and a skill named `sprint` exists in the project (`.claude/skills/sprint/SKILL.md`) or in the user's skills (`~/.claude/skills/sprint/SKILL.md`), stop: tell the user that their own `/sprint` takes precedence, and do nothing else.

## Project profile (mandatory)

Read `.claude/team-skills.json` at the repository root, version 1. Paths are relative to that root; reject absolute paths and paths escaping it.
Require `handoff`, `docs.specifications`, and `docs.tasks`; read `commands.push` to select the commit/push skill (the sole permitted default is `/team-skills:safe-push` if that key is missing). If the profile or any required path key is missing or invalid, stop and name the file/key. Format: `team-skills:init_dev` and `docs/team-skills-profile.md` in the catalog. Do not guess prefixes or use project-specific fallback paths. Resolve `HANDOFF_PATH` to the absolute path from `handoff` and pass it to every `check_authz.py` call. Find task files only under `docs.tasks`, and specifications only under `docs.specifications`.


Autonomous orchestrator for executing a specification. Reads all 🟡 tasks from the spec, groups them into waves by dependencies, and runs each wave in parallel.

---

## Inputs

- `/sprint S02` — interactive mode: show the plan, wait for "да/ок/go" from the user at each checkpoint
- `/sprint S02 --dry-run` — only show the wave plan, execute nothing
- `/sprint --yes S14` — **headless mode for cron/auto-pilot.** The plan checkpoint uses HANDOFF pre-authorization; at checkpoints, instead of stdin, the pre-authorization is read from the profile handoff file (see the "Headless --yes mode" section). When pre-auth does not permit auto-go, `/sprint` pings TG via `scripts/autopilot/tg_ask.sh` and waits for a human click for up to 2 hours via `tg_wait_answer.sh`. For design docs and the checkpoint contract, see `.claude/skills/auto-pilot/SKILL.md`.

If no spec number is passed — report an error and stop:

```text
❌ Укажи номер спецификации: /sprint S02
```

---

## Headless --yes mode

Under `--yes`, implementation checkpoints (never commit/push/merge/PR/branch or worktree deletion) that wait for an answer in interactive mode go through a **three-way decision**:

| Decision | Source | What to do |
|---|---|---|
| `auto` | task is in `pre_authorized_tasks` (HANDOFF YAML) | continue without escalation, log to TG `✓ T125 pre-auth — продолжаю` |
| `ask` | task is in `always_escalate_tasks` or `<checkpoint>_default = ask` | `tg_ask.sh` + `tg_wait_answer.sh` (timeout 7200 = 2 hours). Answer "yes" → continue. "no" → mark ⚠️ blocked. "skip" → mark ⛔ skipped. Timeout → mark ⚠️ blocked with the note "no human reply in 2h". |
| `skip` | rare override | mark the task ⛔ skipped without escalation |

**Technical contract:** at each checkpoint the skill calls:

```bash
DECISION=$(python3 scripts/autopilot/check_authz.py --handoff "$HANDOFF_PATH" --task <TNN> --checkpoint <key>)
```

Possible values of `<key>`: `risky_default`, `deploy_default`, `manual_test_default`, `test_failure_default`, `unplanned_risk_default`. Plan-confirm is checked separately:

```bash
PLAN_OK=$(python3 scripts/autopilot/check_authz.py --handoff "$HANDOFF_PATH" --checkpoint plan_confirmed)  # yes|no
```

If `--yes` is passed but there is no `yaml autopilot` block in HANDOFF → EVERYTHING defaults to `ask`. This is safe.

**Escalation via TG:**

```bash
MSG_ID=$(scripts/autopilot/tg_ask.sh "⚠️ <skill>: <TNN> — нужно решение
<краткая суть>
Файлы: <list>" \
  "✅ Да=yes|❌ Нет=no|⏩ Пропустить=skip")
```

**CRITICAL:** do not call `tg_wait_answer.sh` with timeout > 480 sec — the sub-agent's Bash tool has a hard cap of 600 sec; a long wait will be killed, the sub-agent will see a fake "timeout" and mark the task blocked **before the user has had a chance to click**.

The correct pattern is a retry-loop, up to 12 iterations (96 min total wait):

```bash
ATTEMPT=0
ANSWER=""
while (( ATTEMPT < 12 )); do
  ANSWER=$(scripts/autopilot/tg_wait_answer.sh "$MSG_ID" 480 5)
  RC=$?
  if [[ "$RC" -eq 0 ]]; then break; fi   # got yes/no/skip
  if [[ "$RC" -ne 1 ]]; then break; fi   # error other than timeout — bail
  ATTEMPT=$((ATTEMPT+1))
done
if [[ -z "$ANSWER" || "$ANSWER" == "timeout" ]]; then
  ANSWER="timeout"  # user не ответил за 96 мин → реально blocked
fi
```

ANSWER is in {yes|no|skip|timeout}. The skill interprets it by the checkpoint's context (see the sections below).

**TG logging (normal operation, no blocking):**

In `--yes` mode, ping TG on these events if the channel is configured (log a skipped notification otherwise):
- Wave start: `🟡 Sprint S14 Волна 2/4 — 5 задач [T125 T126 T127 T128 T130]`
- Wave end: `✅ Sprint S14 Волна 2/4 готова — ready to commit`
- Sprint finish: `✅ Sprint S14 закончен — 16/16 задач` (or partial)

For templates and style, see the "TG logging" section in `.claude/skills/auto-pilot/SKILL.md`. Do not duplicate with jargon; keep it to one or two short lines.

---

## Algorithm: Phase 0 — Parse the spec and build waves

### 0.0 — Parse arguments

Extract:
- `spec_id` (e.g. `S14`)
- `--yes` (boolean — headless mode)
- `--dry-run` (boolean)

`--yes` and `--dry-run` may appear in any order relative to `S14`. If both are passed, `--dry-run` wins (the plan is shown, nothing is executed, no escalations are made).

### 0.1 — Find the spec file

Run the search:

```text
glob <docs.specifications>/SNN_*.md
```

If the file is not found — check `<docs.specifications>/*_done.md`.
If still not found → STOP:

```text
❌ Спецификация S02 не найдена в <docs.specifications>/
```

### 0.2 — Collect tasks with status 🟡

Read the spec file. Find all rows in the task table where the status = 🟡.
Extract for each: the TNN number, the title, and the "Зависит от" column (if present).

If there are no 🟡 tasks:

```text
ℹ️ В спецификации S02 нет активных задач (все ✅ или 🔵).
```

Stop.

### 0.3 — Build the dependency graph

**If the spec has an explicit "Зависит от" column:**

- Build the graph from it: TNN → [list of blocking TNNs]

**Fallback — if there is no such column:**

- Treat all tasks as independent → a single wave, executed sequentially (parallelism is not applied without explicit dependencies)

### 0.4 — Split into waves

Wave 1: tasks with no blockers (in-degree == 0)
Wave N: tasks whose blockers are all completed in previous waves

If the graph contains a cycle → STOP:

```text
❌ Обнаружен цикл зависимостей: T05 → T06 → T05
Исправь таблицу зависимостей в спеке и запусти /sprint заново.
```

---

## Algorithm: Phase 1 — Pre-flight plan

### 1.1 — Preliminary risk scan

For each task, read the task file and the acceptance criteria.
Determine the expected stop points (see the "Risk detection" section).

### 1.2 — Output the plan

```text
## Sprint S02 — План

Волна 1: T05 ∥ T07
Волна 2: T06 ∥ T08

Ожидаемые точки остановки для тебя:
  ⚠️  T05 — рискованное изменение (миграция БД)
  🚀  T07 — деплой
  🧪  T06 — ручное тестирование (если авто-тесты не пройдут)

Итого: ~N точек где нужен ты. Продолжать? (да/нет)
```

In `--yes` mode, additionally show the decision for each stop point:

```text
Ожидаемые точки остановки (с pre-auth из HANDOFF):
  ⚠️  T05 — RISKY → auto (T05 ∈ pre_authorized_tasks)
  🚀  T07 — DEPLOY → ask (default)
  🧪  T06 — MANUAL_TEST → ask (default)
```

### 1.3 — If --dry-run

Output the plan and finish. Execute nothing. Do not request confirmation.

### 1.4 — Plan confirmation

**Interactive mode:** wait for "да" / "ок" / "go" from the user. On "нет" / "стоп" — finish.

**`--yes` mode:**

```bash
PLAN_OK=$(python3 scripts/autopilot/check_authz.py --handoff "$HANDOFF_PATH" --checkpoint plan_confirmed)
```

- `PLAN_OK == "yes"` → continue, log to TG `→ Беру: /sprint S14, план auto-confirmed`
- `PLAN_OK == "no"` → ALWAYS escalate (plan not confirmed) — `tg_ask` with the plan text; ANSWER ∈ {yes → continue, no/timeout → finish with outcome=partial}

---

## Algorithm: Phase 2 — Executing waves

### 2.1 — For each wave

Announce the wave start:

```text
## Волна N/M — старт [T05, T07]
```

In `--yes`, additionally: `scripts/autopilot/tg_notify.sh "🟡 Sprint <Spec> Волна N/M — <K задач>"`

When `AUTOPILOT_TICK=1`, never route to `/sprint-codex`, regardless of Codex availability or wave size. Execute all tasks sequentially through `/impl` in the current working tree, without creating worktrees or committing. This tick rule overrides the parallel dispatch below and Step 4's normal implementation routing. Finish with `ready to commit`, the exact file list, proposed commit message and actual verification results under Step 7 (R4); no automatic commit/push.

Outside an autopilot tick, if the wave contains more than one task — run them in parallel via `superpowers:dispatching-parallel-agents`. Each agent receives:

- The TNN task number
- The path to the task file
- An instruction to follow the "Executing a single task" algorithm below
- In `--yes` mode — a flag that it is headless: instead of "waiting for the user", use `check_authz.py` + `tg_ask.sh` + `tg_wait_answer.sh`

If the wave contains a single task — execute it directly (without dispatching an agent).

### 2.2 — Wait for all tasks of the wave to complete

The next wave starts only after ALL tasks of the current wave have completed locally (status: ✅ prepared for review, ⚠️ blocked, or ⛔ skipped). Preparation is not human acceptance or a commit.

### 2.3 — Handling blocked tasks

If a task finished with status ⚠️ blocked or ⛔ skipped:

- All tasks of later waves that depend on it get status ⛔ skipped
- Independent tasks of later waves continue executing

### 2.4 — After the wave

In `--yes`: `scripts/autopilot/tg_notify.sh "✅ Sprint <Spec> Волна N/M готова — ready to commit"` — only when every task of the wave is ✅ prepared for review. A wave with a ⚠️ blocked or ⛔ skipped task sends `⚠️ Sprint <Spec> Волна N/M: готово к ревью K из L, заблокированы: <TNN, …>` instead.

### 2.5 — After all waves

Output the final report, exact file list and proposed commit message. In `--yes`, stop at `ready to commit` and send the same summary through `tg_notify.sh` if configured.

---

## Algorithm: Executing a single task

### Step 1 — Gather context *(in parallel)*

Read in parallel:

- The task file: `<docs.tasks>/TNN_*.md`
- The spec file (already read in Phase 0 — reuse it)
- All code files mentioned in the task
- Related files (imports, configs) if mentioned

Extract from the task: acceptance criteria, the list of files to change, the description.

### Step 2 — Auto-validate the plan

Generate an internal implementation plan. Check the plan against the acceptance criteria.

If some criterion is not covered → STOP:

```text
⛔ T05 — план не покрывает критерии приёмки
Не покрыто:
  - AC#3: уведомление отправляется при изменении статуса сделки
```

Task status → ⚠️ blocked. In `--yes` mode, additionally a TG escalation `🔴 T05 — план не покрывает AC#3` (no need to ask, just notify).

If the plan covers all criteria → continue to step 3.

### Step 3 — Checkpoint (RISKY / DEPLOY)

Determine risks using the rules in the "Risk detection" section.

**Interactive mode, DEPLOY or RISKY found:**

Output the plan with markers, wait for "да/нет/пропустить".

**`--yes` mode:**

For each risk, determine the checkpoint key:
- DEPLOY → `deploy_default`
- RISKY → `risky_default`

```bash
DECISION=$(python3 scripts/autopilot/check_authz.py --handoff "$HANDOFF_PATH" --task <TNN> --checkpoint <key>)
```

- `DECISION=auto` → continue, log to TG `✓ T125 pre-auth для <checkpoint> — продолжаю`
- `DECISION=skip` → task ⛔ skipped, TG `⏩ T125 skipped (HANDOFF directive)`
- `DECISION=ask` → escalate using the retry-loop pattern (see the "Escalation via TG" section at the start of the file). Briefly: `tg_ask.sh` → save `MSG_ID` → `tg_wait_answer.sh "$MSG_ID" 480 5` in a loop up to 12 times.

Interpretation: `yes` → continue, `no` → ⚠️ blocked, `skip` → ⛔ skipped, `timeout` → ⚠️ blocked (log entry "no human reply in 96 min").

**If RISKY and DEPLOY are absent** — the step is skipped.

### Step 4 — Implementation

If the project splits roles — Claude decides, Codex writes the code (its `CLAUDE.md` says so and `/impl` is installed) — Claude does not write executable code here: turn the plan into a brief and hand it to `/impl` — Codex writes the code, Claude reads the diff against the brief. Routing and the exceptions pocket — the project's `runbook_codex_routing.md`, if it has one; an exception is announced in one line. Codex disabled or unavailable is itself an exception: then write the code per the plan yourself. Without such a split — write the code per the plan yourself. Autonomously, without stops.

If an **unplanned risk** is discovered in the process (a pattern from "Risk detection" that was not in the step 2 plan) → IMMEDIATE STOP:

**Interactive mode:** show the new risk, wait for "да/нет/пропустить".

**`--yes` mode:**

```bash
DECISION=$(python3 scripts/autopilot/check_authz.py --handoff "$HANDOFF_PATH" --task <TNN> --checkpoint unplanned_risk_default)
```

Then proceed as in Step 3 (auto/skip/ask).

### Step 5 — Testing

#### Auto-tests

Run the tests of the affected modules. **If the tests pass** → proceed to step 6.

**If the tests fail:**

- Attempt 1: analyze the traceback, find the cause, fix it (when Step 4 went through `/impl`, the fix goes the same way — a follow-up brief with the traceback)
- Attempt 2: after the fix, run the tests again
- Attempt 3: final attempt

After 3 failures:

**Interactive mode:** STOP, wait for instructions.

**`--yes` mode:**

```bash
DECISION=$(python3 scripts/autopilot/check_authz.py --handoff "$HANDOFF_PATH" --task <TNN> --checkpoint test_failure_default)
```

- `auto` → mark ⚠️ blocked (we don't take risks without explicit auth), log to TG
- `skip` → ⛔ skipped, log to TG
- `ask` → `tg_ask` with the last traceback + "yes (try again) / no (stop) / skip"

After receiving instructions — continue or finish with ⚠️ blocked.

#### Manual testing (MANUAL_TEST)

If the task is marked MANUAL_TEST (UI changes without auto-tests):

**Interactive mode:** formulate a scenario, ask the user.

**`--yes` mode:**

```bash
DECISION=$(python3 scripts/autopilot/check_authz.py --handoff "$HANDOFF_PATH" --task <TNN> --checkpoint manual_test_default)
```

- `auto` → skip the manual check (we trust that the task is tested by auto-tests/sub-agent)
- `skip` → ⛔ skipped (the task requires a manual check that won't happen)
- `ask` → `tg_ask` with instructions on what to check + "yes (all good) / no (broken) / skip"

### Step 6 — Review loop

Run the `review-loop` skill for the current task.
The `codereview → fix` loop until `CRITICAL==0 AND HIGH==0`, maximum 5 iterations.
Fixes are applied in fast mode (without waiting for confirmation).

### Step 7 — Prepare for review and explicit approval

Only after a clean review-loop. A loop ending at its limit, plateau, or with a surviving finding leaves the task ⚠️ blocked; show blockers, preserve the changes, and notify TG in `--yes`. Never finalize a blocked task.

After clean review, keep acceptance pending for human review; do not invoke `/accept` as an automatic route to commit/push. Collect the exact files with `git diff --name-only` and `git ls-files --others --exclude-standard`, show the proposed commit message and actual verification results, and finish all waves with a reviewable file list.

Interactive mode: report `ready to commit`, show the concrete file list, proposed message and proposed action, then wait for an explicit human “yes” in this dialogue. Only then invoke the skill selected by `commands.push` (default `/team-skills:safe-push`), limiting it to the approved action/files. Approval for commit alone does not authorize push: ask separately before pushing. Merge, PR creation/merge, branch deletion and worktree deletion each require explicit approval for the concrete action and files too.

`--yes`, cron, HANDOFF/config permissions and TG plan buttons never count as commit/push permission. In headless mode stop with `ready to commit`, report files and the proposed message, and notify via `scripts/autopilot/tg_notify.sh` if configured. Notification failure must be reported; it does not authorize proceeding. No human in chat → no commit/push. Tasks prepared locally can satisfy dependency checks for subsequent waves, but must not be announced as committed, pushed, or accepted.

---

## Risk detection

Scan the files planned to be changed. Risk is determined by patterns:

| Type | Patterns |
|-----|----------|
| `DEPLOY` | deployment manifests, reverse-proxy configs, `.github/workflows/`, container build files |
| `RISKY` | files with `migration`, `migrate`, `auth`, `password`, `token`, `SECRET`, env variables, external APIs (Bitrix, YooKassa, Supabase) |
| `MANUAL_TEST` | changes in `src/app/keyboards/`, `src/app/texts/`, message templates, UI handlers without unit tests |

**Unplanned risk** — a pattern discovered during implementation (step 4) that was not in the step 2 plan.

---

## Final report

After all waves are complete:

```text
## Sprint S02 — Итог

Статус: ready to commit
Файлы: <конкретный список>
Сообщение коммита: <предложение>
Коммит/пуш: ожидают явного согласия в чате

| Задача | Статус     | Точки остановки        | Комментарий                   |
|--------|------------|------------------------|-------------------------------|
| T05    | ✅ prepared | 1 (RISKY — pre-auth)   | --yes auto                    |
| T07    | ✅ prepared | 2 (DEPLOY, MANUAL_TEST)| --yes ask → yes (TG ответ)    |
| T06    | ✅ prepared | 0                      | —                             |
| T08    | ⚠️ blocked | —                      | TG-ask timeout 2h             |

Волн: 2 | Задач выполнено: 3/4 | Точек остановки: 3 (1 auto, 1 ask-yes, 1 timeout)

Требуют внимания:
  ⚠️ T08 — нет ответа в TG за 2 часа. Запусти /sprint S02 заново когда сможешь.
```

In `--yes`: a one-line TG summary `<emoji> Sprint <Spec> закончен — <K>/<Total> prepared, <B> blocked, <S> skipped`.

---

## Rules

- **DEPLOY — always a checkpoint** (in interactive mode it waits for stdin; in --yes — via `deploy_default`/per-task)
- **RISKY — always a checkpoint** (likewise)
- **3 attempts for tests**: after failure — escalation
- **Unplanned risk → immediate STOP**: discovered in the process → checkpoint
- **A blocked task does not block the wave**: other tasks of the same wave continue
- **Dependents of a blocked task → automatically skipped**: do not attempt to execute
- **Dependency cycle → STOP at the start**
- **--dry-run → plan only** (even with --yes — the plan is output with markers, nothing is executed)
- **Fallback without dependencies → sequentially**
- **Every commit/push requires explicit human approval** for the exact action/files (Step 7); headless stops at `ready to commit`.
- **Code goes through `/impl`** when the project splits roles (Step 4): Claude writes the brief and reads the diff; writing code itself only under the exceptions pocket, announced
- **--yes without a HANDOFF YAML block → everything defaults to `ask`**. If TG creds are also not configured — `/sprint --yes` refuses to start with the error "No HANDOFF authz + no TG creds = no autonomy possible"

---

## See also

- **`/auto-pilot`** — orchestrator-router. In cron mode it is the one that calls `/sprint --yes`. The TG template design and checkpoint contract are there.
- **`/sprint-codex`** — parallel implementation of wave tasks via Codex workers in a git worktree. Outside an autopilot tick, routing selects it automatically if Codex is available and the wave has ≥2 tasks. With `AUTOPILOT_TICK=1`, always use sequential `/impl` in the current tree instead (Phase 2.1), ending at `ready to commit`. See spec S11.
- **`/codex-toggle`** — switching classic ↔ codex.
- **`/review-loop`** — the review loop after implementing a task (Step 6).
- **`commands.push`** — the profile-selected skill, invoked only for an explicitly approved action (Step 7).
