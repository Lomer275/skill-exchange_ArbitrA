---
name: auto-pilot
description: Autonomous orchestrator-router for the SUP project. ONE TICK = one decision = one action. Does not run the sprint/review/accept itself — it picks which existing skill (/sprint, /sup-spec-writer, /review-loop, /accept) to invoke based on the repository state. Use when the user says '/auto-pilot', '/auto-pilot --dry-run', 'запусти автопилот', 'один тик автопилота', 'автономный режим', 'прогони цикл сам', 'возьми следующую задачу', 'оркестрируй сам', 'тик автопилота', or when a cron trigger is configured. Includes mandatory stop-lines (red CI on main, ban on destructive git operations) and logs every tick to autopilot_log.md. Escalates via a dedicated devops TG bot when stuck.
---

# /auto-pilot — orchestrator-router

You are not an executor but a **dispatcher**. The existing skills (`/sprint`, `/sup-spec-writer`, `/review-loop`, `/codereview-dual-loop`, `/accept`, `/sup-push`, `superpowers:finishing-a-development-branch`) already know how to do the work end-to-end. Your job is to look at the repo state and decide **what to invoke right now**.

## Key principle: one tick = one decision

Do not try to "work around the clock" — it is unstable and expensive. One `/auto-pilot` run = one action. The chain of autonomy is built through **repeated cron runs**, not through a long session. Fresh context every time → less drift, easier to debug, easier to roll back.

After execution, **finish** and leave a clear log.

---

## Inputs

- `/auto-pilot` — a normal tick: read state, choose an action, execute it, report
- `/auto-pilot --dry-run` — show **what it would do**, without doing anything (preview)
- `/auto-pilot --status` — only show status (kill-switch, last_tick, budget) and exit

If anything else arrives (for example `/auto-pilot S05`) — throw an error, do not try to interpret it.

---

## TG logging (live visibility)

The autopilot writes to TG @lobster_21 at key moments. The goal is to **read it from your phone in 3 seconds** and understand "what the robot is doing right now". No jargon, no class hashes, no counters for the sake of counters.

**Message style rules:**
- Russian, conversational («взял», «сделал», «не получилось» — not «executed», «processed»).
- Emoji as a status marker at the start: 🤖 (start), 🎯 (decision), ✅ (done), 🟡 (in progress), ✓ (small success inside), ⚠️ (decision needed), 🔴 (failed), 😴 (nothing to do).
- Give **enough detail**: what you are about to do / what you did / which files / how many tests / commit. **Do not give a wall of text**: 5-10 lines maximum; if more — a pointer to `autopilot_log.md`.
- Clarify context: if the state is non-obvious (5/16 tasks closed) — report progress. If there are stop-plans (T126/T130) — name them in advance so the person is ready for pings.
- Short hashes (7 characters), no more than 5 commits in a list.
- Length of a single task in a list: one line with specifics («T125: payload schemas, 12 тестов»), not «T125 done».

**Templates (via `scripts/autopilot/tg_notify.sh "<text>"`):**

| Point | Message template |
|---|---|
| Cron tick starts (wrapper) | `🤖 Автопилот стартует (HH:MM Z)`<br>`Ветка: dev @ <sha>`<br>`Последний коммит: <commit title>`<br>`Из HANDOFF: <directive>`<br>` `<br>`Читаю состояние, выбираю действие.` |
| Decision made (phase 3) | `🎯 Решение: Rule X — <как назвал правило>`<br>`Беру: /sprint --yes S14 (Wave 2 из 4)`<br>`Состояние: 5/16 задач S14 закрыто, осталось 11`<br>`В очереди этой волны: T125 T126 T127 T128 T130`<br>`Стопы: T126 (Bitrix) и T130 (UI) попросят клик` |
| Wave started | `🟡 Sprint S14 Волна 2/4 — старт`<br>`Auto-go: T125 T127 T128 (параллельно)`<br>`Будут ждать клика: T126 T130`<br>`Ожидаемое время: 15–25 минут` |
| Task closed within a wave | `✓ T125 закрыто — payload schemas`<br>`12 unit-тестов passed, 3 файла изменено`<br>`Коммит: <sha>` |
| Wave done | `✅ Sprint S14 Волна 2/4 готова (24 мин)`<br>`Закрыто 5/5 задач:`<br>`• T125 — payload schemas (12 тестов)`<br>`• T127 — validate_payment_data (8 тестов)`<br>`• T128 — snapshot_history (15 тестов)`<br>`• T126 — Bitrix sync (ты подтвердил, 24 теста)`<br>`• T130 — UI шаблоны (ты подтвердил, ручная проверка)`<br>`Коммит: <sha> → dev`<br>`Прогресс: 10/16 задач S14` |
| Decision needed (RISKY/DEPLOY/MANUAL_TEST) | via `tg_ask.sh` with buttons:<br>`⚠️ T126 — нужно решение`<br>`Bitrix sync cron, греди recompute + advisory lock`<br>`Файлы: Handler/payments/sync.py`<br>`Внешние API: Bitrix REST (read-write по deal.list)`<br>`Тесты: будут написаны после фикса`<br>` `<br>`Ответь: ✅ да / ❌ нет / ⏩ пропустить` |
| Tick finished successfully | `✅ Автопилот закончил тик`<br>`Длительность: 24 мин`<br>`Ветка: dev @ <sha>`<br>`Сделал: <короткое описание>`<br>`Новых коммитов: <N>`<br>`Прогресс: 10/16 задач S14`<br>`Дальше: следующий тик в 18:00 МСК — Wave 3` |
| Tick idle (nothing to do) | `😴 Делать нечего`<br>`HANDOFF пуст / нет активных задач`<br>`Последняя проверка: HH:MM`<br>`CI на main: success`<br>`Жду следующего тика (18:00 МСК)` |
| Tick failed/stuck | `🔴 Тик застрял`<br>`Где: T127, Step 5 (test failures)`<br>`Что: 3 попытки фикса не помогли. Последняя ошибка:`<br>`AssertionError: expected 200, got 500`<br>` `<br>`Подробности: autopilot_log.md`<br>`Нужно: посмотри лог и скажи как чинить` |

**Anti-patterns (do not do this):**
- ❌ `Autopilot tick #1 done — S14 Wave 1 (5/16 tasks)` ← English, tick numbering is useless
- ❌ A list of all TNNs with descriptions ← in TG this is a wall of text
- ❌ A feed of 3–5 commits with descriptors ← that is for git log

**A "before / after" example (based on the Wave 1 result):**

Before (a wall of text):
```
🤖 Autopilot tick #1 done — S14 Wave 1 (5/16 tasks)
✅ T119 Models (PaymentObligation/DealDebtSnapshot/History/ManagerTaskLink) + migration 0016 — 7 tests
✅ T120 cases_mapper +9 keys — 9 tests
...
Commits: 82e6052 (T119, message mismatch) + d1fa4c2 (Wave 1 clean)
Branch: dev (pushed)
Wave 2-4 (11 tasks) — отложены. /sprint в headless cron-режиме требует --yes mode (backlog).
Log: docs/5. SUP-unsorted/autopilot_log.md
```

After:
```
✅ Автопилот закончил волну
Сделал 5 задач из 16 (волна 1/4) — модели + утилиты + EventType
Запушил: dev @ d1fa4c2
Дальше — волна 2 (5 задач, есть стопы)
```

If the person wants details — they will open `autopilot_log.md`. TG is "how things are going" at a glance.

All `tg_notify.sh` calls are non-fatal: if TG is unavailable, the autopilot does not crash, notes it in the log, and continues.

---

## Phase 0 — Kill-switch and state

### 0.1 Check the kill-switch

Read `.claude/autopilot.json`. If the file does not exist — create it with the defaults (see below) and **exit with the note "first run, check the config"** — do not take any actions on the first tick.

```json
{
  "enabled": false,
  "last_tick_at": null,
  "ticks_today": 0,
  "tokens_today": 0,
  "budget": {
    "max_ticks_per_day": 8,
    "max_tokens_per_day": 5000000
  },
  "escalation": {
    "tg_bot_token_env": "AUTOPILOT_TG_BOT_TOKEN",
    "tg_chat_id_env": "AUTOPILOT_TG_CHAT_ID"
  },
  "whitelist_paths": ["**"],
  "blacklist_paths": [],
  "require_human_approval_paths": [
    "Handler/migrations/**",
    "Tracker/migrations/**",
    ".github/workflows/**"
  ]
}
```

If `enabled: false` → exit with a clear message. No actions.

### 0.2 Check the budget

If today (by the UTC day of `last_tick_at`) `ticks_today >= max_ticks_per_day` or `tokens_today >= max_tokens_per_day` has already been reached → exit with the note "budget exhausted, wait a day or a manual reset".

### 0.3 Reset the daily counters

If `last_tick_at` < today (UTC) → reset `ticks_today` and `tokens_today` to 0 before incrementing.

---

## Phase 1 — Read the state of the world

These are the orchestrator's "eyes". Do it **in parallel** (one Bash batch + one Read batch):

1. **Bash batch:**
   - `git status --short`
   - `git log --oneline -5`
   - `gh run list --branch main --limit 3 --json status,conclusion,createdAt,name`
   - `gh pr list --state open --json number,title,headRefName,statusCheckRollup --limit 10`
   - `ls "docs/3. SUP-tasks/" | head -40` (excluding Done/)
   - `ls "docs/2. SUP-specifications/" | head -20`

2. **Read batch:**
   - `SUP-HANDOFF.md` (first 200 lines)
   - Today's `autopilot_log.md` if it exists

Put all of this into your context. **Do not do a detailed analysis of the tasks** — that comes in phase 3 and only for the winner.

---

## Phase 2 — Stop-lines (hard)

Before doing anything, check all the red flags. Any one = an immediate stop with escalation:

| Condition | Action |
|---|---|
| The latest `deploy-prod` run on main = `failure` or `cancelled` | STOP + escalate `🔴 CI на main красный (run #X). Автопилот замёрз до ручного резолва.` |
| `git status` shows unmerged conflicts / detached HEAD | STOP + escalate `⚠️ Репо в нестандартном состоянии: <git status>` |
| Branch ≠ `dev` (or the one explicitly set in `autopilot.json:branch.work_branch`) | STOP + escalate `⚠️ Текущая ветка <X>, ожидалась <work_branch>` |
| HANDOFF.md contains the line `⛔ AUTOPILOT_PAUSE` | STOP without escalation, this is your deliberate pause |

**Under no circumstances** do: `git push --force`, `git reset --hard`, `git checkout --`, `gh pr merge`, `gh pr close --delete-branch`, `rm -rf`, or deletion of task/spec files. This is an **architectural ban** — even if review-loop or another skill suggests it. In such cases — STOP + escalate.

---

## Phase 3 — Decision rules (what to invoke)

Pick the **first matching** rule from top to bottom:

### Rule 1 — Explicit directive in HANDOFF

Does `SUP-HANDOFF.md` have a section **«🤖 Автопилот: следующее»** specifying a **concrete skill or slash command** (for example `/sprint --yes S14`)?

→ **Invoke THAT skill via the Skill tool with the given arguments.** Do not substitute it with an "equivalent", do not do partial work by hand, do not "optimize the scope due to budget". The person already made these decisions when they wrote the directive.

The override priority from the person = the autopilot is a **dispatcher**, not an **editor of intent**. If you think the directive is suboptimal — leave a note in the log and still invoke it as specified. On the next tick the person will adjust the HANDOFF.

**Anti-pattern:**
- ❌ HANDOFF: `/sprint --yes S14` → the autopilot decided "closing out T125 is cheaper, I'll do that instead of the sprint"
- ❌ HANDOFF: `/sprint --yes S14` → the autopilot did part of the sprint itself in the main thread without invoking the Skill

**Right:**
- ✅ HANDOFF: `/sprint --yes S14` → `Skill(skill="sprint", args="--yes S14")` → full handoff of control to /sprint

If the directive is empty, absent, or points to a nonexistent skill — go to Rule 2.

### Rule 2 — Unfinished cycle

Does `git status` show uncommitted changes **in the whitelist zone**?
→ This is an unfinished previous tick. Finish it:
- If there is a latest task in `autopilot_log.md` without a "closed" entry → invoke `/accept TNN`, then `/sup-push`
- Otherwise → STOP + escalate `⚠️ Несоммиченные изменения без следа в логе, разберись.`

### Rule 3 — A ready, active task

Does `docs/3. SUP-tasks/` have a `TNN_*.md` with YAML frontmatter `status: active` and no blockers (in the frontmatter `blocked_by:` is empty or all blockers are in Done/)?

→ Pick the task with the smallest NN. If there are several in one spec → invoke `/sprint S0X` (it will sort out the waves itself). If there is a single task — also via `/sprint S0X` (that is its contract).

**Do not run a task if it touches `require_human_approval_paths` — escalate instead.**

### Rule 4 — A draft spec for decomposition

Does `docs/2. SUP-specifications/` have an `SNN_*.md` with `status: draft` and **without** corresponding TNN files in `docs/3. SUP-tasks/`?

→ Invoke `/sup-spec-writer` with the command "decompose SNN into tasks". **Mark this with ⚠️ in the log** — the person must review the result in the morning.

After decomposition — **do not run /sprint in the same tick**. Finish; the next tick will pick it up.

### Rule 5 — An open PR with green CI

Is there an open PR from `dev` (or `branch.work_branch` from the config) into `main` with `statusCheckRollup` = SUCCESS that you created earlier (there is a note in `autopilot_log.md`)?

→ **Do not merge**. Just note in the log "PR #X is ready for human review" and finish. A merge into main = your person.

### Rule 6 — Idle

Nothing above matches → write "idle, nothing to do" in the log, update `last_tick_at`, exit. This is normal.

---

## Phase 4 — Execute one action

Invoke the chosen skill via the Skill tool. **Hand full control over to it** — it will do its own work. When control returns:

- If the inner skill returned success → go to phase 5
- If the inner skill got stuck / asked for confirmation / hit an error → go to phase 6 (escalate)
- If you yourself did not get a response within a reasonable time (for example `/sprint` > 30 minutes) — escalate with the note "possibly stuck"

### After a successful `/sprint` — finalize the branch

`/sprint` already does review-loop → accept → push itself. But the decision of "what to do next with the branch" (PR into main? leave it pushed?) — invoke `superpowers:finishing-a-development-branch`. It will look at the context and pick the right option.

**Override**: you do NOT merge into main and do NOT create a ready-for-review PR. If `finishing-a-development-branch` wants to merge → stop it, create a draft PR instead of the merge, leave it for the person.

---

## Phase 5 — Verify and log

### 5.1 Verify

Before saying "done" — invoke `superpowers:verification-before-completion` to check:
- The tests the skill promised → actually run and green?
- The files that should have changed → actually in the diff?
- Git status → the expected state?

If verification failed → fix or escalate. Do not write "done" if it is not verified.

### 5.2 Log

Append a line to `docs/5. SUP-unsorted/autopilot_log.md` (create it if it does not exist):

```markdown
## 2026-05-13 14:23 UTC — tick #N (TNN_xxx)
- **Решение**: Rule 3 → /sprint S08
- **Действие**: ran /sprint S08 → 3 tasks completed (T067, T068, T069)
- **Verify**: ✅ pytest passed, git status clean
- **Branch**: dev @ <sha>
- **Tokens**: ~340k
- **Outcome**: success
- **Next**: idle ожидается на следующем тике
```

### 5.3 Update the state

In `.claude/autopilot.json`:
- `last_tick_at` = current UTC ISO
- `ticks_today` += 1
- `tokens_today` += approx tokens used

### 5.4 (Optional) Update the HANDOFF

If you completed a substantive task — add a short line to the **«Завершено автопилотом»** section in the HANDOFF. If it does not exist — create it.

---

## Phase 6 — Escalation

When stuck or a stop-line triggered:

### 6.1 Write to the log as in phase 5, but with outcome=blocked

```markdown
## 2026-05-13 04:12 UTC — tick #N — ❌ BLOCKED
- **Триггер**: Rule 3 → /sprint S09 T072
- **Действие**: /sprint упал на review-loop iteration 4 (бесконечный цикл по handler/auth.py)
- **Outcome**: blocked
- **Нужно решение**: handler выдаёт два разных типа ошибок при разных входах — нужна продакт-логика
- **Артефакт**: docs/5. SUP-unsorted/autopilot_blocked_T072.md (детали)
```

### 6.2 TG ping (if configured)

If `AUTOPILOT_TG_BOT_TOKEN` and `AUTOPILOT_TG_CHAT_ID` are set in the env:

```bash
curl -fsSL -X POST "https://api.telegram.org/bot${AUTOPILOT_TG_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${AUTOPILOT_TG_CHAT_ID}" \
  --data-urlencode "text=🤖 Autopilot blocked — tick #N
T072: <детали>
Лог: docs/5. SUP-unsorted/autopilot_log.md"
```

**Important:** do not use `parse_mode=Markdown` or `MarkdownV2`. The message content may contain `_`, `*`, `[`, `]`, slashes (`/auto-pilot`, `--dry-run`) — Telegram will bounce it with a 400 parsing error. Plain text is safer, and informativeness does not suffer.

Use `--data-urlencode` (not `-d`) — otherwise special characters in `<детали>` may break the request.

If the env vars are absent (empty `AUTOPILOT_TG_BOT_TOKEN` or `AUTOPILOT_TG_CHAT_ID`) — note this in the log ("TG escalation skipped: no AUTOPILOT_TG_BOT_TOKEN/CHAT_ID"). Do not crash.

### 6.3 Set the pause flag

Prepend to `SUP-HANDOFF.md`:
```markdown
⛔ AUTOPILOT_PAUSE — застрял на tick #N, см. autopilot_log.md
```

This will enable the "stop without escalation" rule (phase 2) for the following ticks until you manually remove the line.

---

## What to tell the user

In `--dry-run` mode:
```
DRY-RUN tick preview:
- Состояние: <одна строка>
- Решение: Rule X → <skill>
- Если запустить — будет вызвано: <skill> с аргументами <args>
- Stop-линии: ✅ все ок / ❌ <какая упала>
```

In normal mode — a short summary:
```
✅ tick #N done
- Rule 3 → /sprint S08 → 3 задачи закрыты (T067-T069)
- Лог: docs/5. SUP-unsorted/autopilot_log.md
- Budget: 3/8 тиков, ~340k/5M токенов
```

On escalation:
```
🔴 tick #N BLOCKED
- Причина: <одна строка>
- Эскалировано: TG ping отправлен / TG ping skipped
- Пауза: ⛔ AUTOPILOT_PAUSE добавлено в HANDOFF
- Детали: docs/5. SUP-unsorted/autopilot_log.md
```

---

## What NOT to do (important)

1. **Do not create new SNN specs.** Specs are the person's domain (via `/spec-brainstorm`). You only decompose existing draft specs into tasks (Rule 4).
2. **Do not merge into main and do not create a ready-for-review PR.** A draft PR at most. The merge is the person's job.
3. **Do not force-push / reset --hard / any destructive git operations.** Never. Even if review-loop suggests it.
4. **Do not interpret CLAUDE.md instructions expansively.** If `migrations/` is not in whitelist-paths — do not touch it even if the task formally requires it.
5. **Do not pick up tasks with `blocked_by` ≠ Done.** Be a stickler.
6. **Do not take two actions in one tick.** Decomposed a draft → STOP. Did /sprint → STOP. Finalized the branch via finishing-a-development-branch → STOP. The next tick will pick it up.
7. **Do not lie in the log.** If verify did not pass — write "outcome: partial/blocked". The log is for you on the following ticks.

---

## Links to other skills

| Skill | When the autopilot calls it |
|---|---|
| `/sprint S0X` | Rule 3 — the main working call |
| `/sup-spec-writer` | Rule 4 — decomposition of a draft spec |
| `/accept TNN` | Rule 2 — finish off an unclosed cycle (rarely, usually inside /sprint) |
| `/sup-push` | Rule 2 — after accept |
| `superpowers:verification-before-completion` | Phase 5.1 — always after an action |
| `superpowers:finishing-a-development-branch` | After /sprint — decide what to do with the branch (with an override of "do not merge into main") |
| `superpowers:systematic-debugging` | If something strange failed in phase 4 and you want to triage before escalation |

**Never invoke directly:** `/codereview`, `/codereview-dual` (these are already inside the loop skills), `/codex-setup`, `/codex-toggle`, `/init_dev`, `skill-creator`.

---

## Cron mode

When invoked from a `CronCreate` job (not interactively):
- Do not ask the person questions (use `AskUserQuestion` only in --dry-run)
- If you find a situation that requires human judgment → escalate, do not block
- Stay silent on success cases (no push notifications for "all good")

Recommended schedule (UTC): `0 6,10,14,18 * * 1-5` — 4 ticks on weekdays, in MSK morning/midday/afternoon/evening.

---

## Future extensions (NOT for v1)

Do not implement, just keep in mind:
- Parallel ticks via worktrees
- Auto-merge into main under certain conditions (refactorings without logic)
- Self-learning from autopilot_log.md (analysis of what blocks often)
- Integration with `/sprint-codex` for waves of ≥2 tasks

For v1 — only sequential ticks and a draft PR at most.
