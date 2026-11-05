---
name: auto-pilot
description: "Autonomous orchestrator-router for repositories with a team-skills profile and an installed autopilot. ONE TICK = one decision = one action. Does not run the sprint/review itself — it picks which existing skill (/sprint, the configured spec writer, /review-loop) to invoke based on the repository state. Use when the user says '/auto-pilot', '/auto-pilot --dry-run', 'запусти автопилот', 'один тик автопилота', 'автономный режим', 'прогони цикл сам', 'возьми следующую задачу', 'оркестрируй сам', 'тик автопилота', or when a cron trigger is configured. Includes mandatory stop-lines (red CI on main, ban on destructive git operations) and logs every tick to autopilot_log.md. Escalates via a dedicated devops TG bot when stuck. If the project or the user has its own `auto-pilot` skill, that one takes precedence — use this one only when the user typed `/team-skills:auto-pilot` or no such skill exists."
---

# /auto-pilot — orchestrator-router

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:auto-pilot` and a skill named `auto-pilot` exists in the project (`.claude/skills/auto-pilot/SKILL.md`) or in the user's skills (`~/.claude/skills/auto-pilot/SKILL.md`), stop: tell the user that their own `/auto-pilot` takes precedence, and do nothing else.

## Project profile (mandatory)

Read `.claude/team-skills.json` at the repository root, version 1. Paths are relative to that root.
Require `handoff`, `docs.specifications`, `docs.tasks`, `docs.tasks_done`, `docs.unsorted`, and `commands.spec_writer`. Missing/invalid profile or required key → stop, name it, and point to `team-skills:init_dev` and `docs/team-skills-profile.md` in the catalog. No guessed prefix or project-specific fallback paths. Reject absolute paths and paths escaping the repository. In this document, `<handoff>`, `<docs.tasks>`, `<docs.tasks_done>`, `<docs.specifications>`, and `<docs.unsorted>` mean the corresponding resolved profile paths. `commands.spec_writer` selects the decomposition skill. Do not read `commands.push`: ticks never commit or push.

## Tick permissions (mandatory)

A tick that prepares changes ends with `ready for review/commit` after listing files (including untracked files), proposing a commit message, reporting actual verification results, and notifying TG through `scripts/autopilot/tg_notify.sh` if configured. Headless execution must stop there. No commit, push, merge, rebase, PR creation/merge, branch deletion, or worktree deletion during a tick, including through a nested skill. Never hand off to `/accept`, a push skill, or `finishing-a-development-branch`.

`--yes`, cron, HANDOFF/config pre-authorization, and TG plan buttons do not authorize these actions. Outside a tick, each action needs an explicit human “yes” in this dialogue for the concrete action and concrete file list; commit permission does not authorize push.

`run_tick.sh` retains `--permission-mode bypassPermissions`. The PATH git guard is the only technical barrier for git in the tick. It allows `status`, `diff`, `log`, `show`, `rev-parse`, `ls-files`, `rev-list`, `merge-base`, `blame`, `cat-file`, `describe`, `for-each-ref`, `ls-tree`, `shortlog`, `grep`, `name-rev`, `show-ref`, and `ls-remote`. It also allows viewing branches (no arguments, `--show-current`, `--list`, `-a`, `-r`, `-v`, `-vv`, `--contains`, `--merged`, `--no-merged`; the last three accept a ref value), `worktree list`, `remote` with no arguments or `-v`, `remote show` (optionally `-n`), `remote get-url` (optionally `--push`/`--all`), and `config --get`, `--get-all`, `--get-regexp`, `--list`/`-l`. Fetch is allowed except with `--upload-pack` or `-u` (including attached values/short-option combinations). Every other command/form, including writes, unknown aliases and leading `-c`, is denied with code 100; configuration errors also fail closed. Supported leading options (`-C`, `--git-dir`, `--work-tree`, `--no-pager`, `--paginate`, `--no-optional-locks`) remain available. It is a PATH shim, not a sandbox: do not use an absolute git executable or change PATH/config to bypass it. The guard does not intercept `gh`; `gh pr create`, `gh pr merge`, and other mutating `gh` operations are forbidden by these instructions. Read-only CI/PR queries remain available.

You are not an executor but a **dispatcher**. The existing skills (`/sprint`, the profile-selected spec writer, `/review-loop`, `/codereview-dual-loop`) already know how to do the work end-to-end. Your job is to look at the repo state and decide **what to invoke right now**.

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
| Cron tick starts (wrapper) | `🤖 Автопилот стартует (HH:MM Z)`<br>`Ветка: <work_branch> @ <sha>`<br>`Последний коммит: <commit title>`<br>`Из HANDOFF: <directive>`<br>` `<br>`Читаю состояние, выбираю действие.` |
| Decision made (phase 3) | `🎯 Решение: Rule X — <как назвал правило>`<br>`Беру: /sprint --yes S14 (Wave 2 из 4)`<br>`Состояние: 5/16 задач S14 закрыто, осталось 11`<br>`В очереди этой волны: T125 T126 T127 T128 T130`<br>`Стопы: T126 (Bitrix) и T130 (UI) попросят клик` |
| Wave started | `🟡 Sprint S14 Волна 2/4 — старт`<br>`Auto-go: T125 T127 T128 (параллельно)`<br>`Будут ждать клика: T126 T130`<br>`Ожидаемое время: 15–25 минут` |
| Task prepared within a wave | `✓ T125 готово к ревью — payload schemas`<br>`12 unit-тестов passed, 3 файла изменено`<br>`Статус: ready for review/commit` |
| Wave done | `✅ Sprint S14 Волна 2/4 готова (24 мин)`<br>`Подготовлено 5/5 задач:`<br>`• T125 — payload schemas (12 тестов)`<br>`• T127 — validate_payment_data (8 тестов)`<br>`• T128 — snapshot_history (15 тестов)`<br>`• T126 — Bitrix sync (ты подтвердил, 24 теста)`<br>`• T130 — UI шаблоны (ты подтвердил, ручная проверка)`<br>`Статус: ready for review/commit`<br>`Прогресс: 10/16 задач S14` |
| Decision needed (RISKY/DEPLOY/MANUAL_TEST) | via `tg_ask.sh` with buttons:<br>`⚠️ T126 — нужно решение`<br>`Bitrix sync cron, греди recompute + advisory lock`<br>`Файлы: <a matched require_human_approval_paths entry from .claude/autopilot.json>`<br>`Внешние API: Bitrix REST (read-write по deal.list)`<br>`Тесты: будут написаны после фикса`<br>` `<br>`Ответь: ✅ да / ❌ нет / ⏩ пропустить` |
| Tick finished successfully | `✅ Автопилот закончил тик`<br>`Длительность: 24 мин`<br>`Ветка: <work_branch> @ <sha>`<br>`Сделал: <короткое описание>`<br>`Статус: ready for review/commit`<br>`Прогресс: 10/16 задач S14`<br>`Дальше: человек проверяет diff и решает о коммите/пуше` |
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
Log: <docs.unsorted>/autopilot_log.md
```

After:
```
✅ Автопилот закончил волну
Сделал 5 задач из 16 (волна 1/4) — модели + утилиты + EventType
Статус: ready for review/commit
Дальше — проверка diff человеком
```

If the person wants details — they will open `autopilot_log.md`. TG is "how things are going" at a glance.

All `tg_notify.sh` calls are non-fatal: if TG is unavailable, the autopilot does not crash, notes it in the log, and continues.

---

## Phase 0 — Kill-switch and state

### 0.1 Check the kill-switch

Read `.claude/autopilot.json`. If it is missing or invalid, stop and ask the user to install/configure autopilot with `install.sh`; do not take any tick action. The installer copies `templates/autopilot.json` with `enabled: false`, a neutral `require_human_approval_paths` list (including `**/migrations/**`), and `destructive_git_ops_forbidden`. Never infer approval-sensitive paths from a particular project's layout.

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
   - `ls "<docs.tasks>/" | head -40` (excluding `<docs.tasks_done>`)
   - `ls "<docs.specifications>/" | head -20`

2. **Read batch:**
   - `<handoff>` (first 200 lines)
   - Today's `autopilot_log.md` if it exists

Put all of this into your context. **Do not do a detailed analysis of the tasks** — that comes in phase 3 and only for the winner.

---

## Phase 2 — Stop-lines (hard)

Before doing anything, check all the red flags. Any one = an immediate stop with escalation:

| Condition | Action |
|---|---|
| The latest `deploy-prod` run on main = `failure` or `cancelled` | STOP + escalate `🔴 CI на main красный (run #X). Автопилот замёрз до ручного резолва.` |
| `git status` shows unmerged conflicts / detached HEAD | STOP + escalate `⚠️ Репо в нестандартном состоянии: <git status>` |
| Branch ≠ `autopilot.json:branch.work_branch` (default `autopilot` — a branch off `origin/main`; create it with `git switch -c autopilot origin/main` before enabling). The deploy branch (`main` where a push to it deploys to prod) is never a work branch, and neither is a long-abandoned branch that has drifted far behind `main` | STOP + escalate `⚠️ Текущая ветка <X>, ожидалась <work_branch>` |
| `<handoff>` (the file from the profile's `handoff` key) contains the line `⛔ AUTOPILOT_PAUSE` | STOP without escalation, this is your deliberate pause |

**Under no circumstances** do: `git push --force`, `git reset --hard`, `git checkout --`, `gh pr merge`, `gh pr close --delete-branch`, `rm -rf`, or deletion of task/spec files. This is an **architectural ban** — even if review-loop or another skill suggests it. In such cases — STOP + escalate.

---

## Phase 3 — Decision rules (what to invoke)

Pick the **first matching** rule from top to bottom:

### Rule 1 — Explicit directive in HANDOFF

Does `<handoff>` have a section **«🤖 Автопилот: следующее»** specifying a **concrete skill or slash command** (for example `/sprint --yes S14`)?

→ **Invoke THAT skill via the Skill tool with the given arguments only within tick permissions.** A directive requesting commit/push/merge/PR or deletion of branches/worktrees must stop for human review in chat; it never overrides the tick restrictions. Do not substitute it with an "equivalent", do not do partial work by hand, do not "optimize the scope due to budget". The person already made these decisions when they wrote the directive.

The override priority from the person = the autopilot is a **dispatcher**, not an **editor of intent**. If you think the directive is suboptimal — leave a note in the log and still invoke it as specified. On the next tick the person will adjust the HANDOFF.

**Anti-pattern:**
- ❌ HANDOFF: `/sprint --yes S14` → the autopilot decided "closing out T125 is cheaper, I'll do that instead of the sprint"
- ❌ HANDOFF: `/sprint --yes S14` → the autopilot did part of the sprint itself in the main thread without invoking the Skill

**Right:**
- ✅ HANDOFF: `/sprint --yes S14` → `Skill(skill="sprint", args="--yes S14")` → full handoff of control to /sprint

If the directive is empty, absent, or points to a nonexistent skill — go to Rule 2.

### Rule 2 — Unfinished cycle

Does `git status` show uncommitted changes **in the whitelist zone**?
→ Preserve the changes and stop at `ready for review/commit`. Show files, proposed commit message, and verification evidence; notify TG if configured. If the last log entry is blocked, keep `outcome=blocked` and escalate instead. Never invoke `/accept` or a push skill to finish an earlier tick.

### Rule 3 — A ready, active task

Does `<docs.tasks>/` have a `TNN_*.md` with YAML frontmatter `status: draft`, whose spec (under `<docs.specifications>`) header says `**Статус:** active` (the person handed it off for work), and no blockers (frontmatter `depends_on:` is empty or every listed TNN is in `<docs.tasks_done>`)? The schema is `task_decomposition_guide.md` §4.0: there is no `status: active` for tasks and no `blocked_by:`; `in_progress` is already being worked on — do not start it again.

→ Pick the task with the smallest NN. If there are several in one spec → invoke `/sprint S0X` (it will sort out the waves itself). If there is a single task — also via `/sprint S0X` (that is its contract).

**Do not run a task if it touches `require_human_approval_paths` — escalate instead.**

### Rule 4 — A draft spec for decomposition

Does `<docs.specifications>/` have an `SNN_*.md` with the header line `**Статус:** draft` (specs keep the status in that line, not in YAML) and **without** corresponding TNN files in `<docs.tasks>/`?

→ Invoke `<commands.spec_writer>` with the command "decompose SNN into tasks". **Mark this with ⚠️ in the log** — the person must review the result in the morning.

After decomposition — **do not run /sprint in the same tick**. Finish; the next tick will pick it up.

### Rule 5 — An open PR with green CI

Is there an open PR from `branch.work_branch` (from the config) into `main` with `statusCheckRollup` = SUCCESS that you created earlier (there is a note in `autopilot_log.md`)?

→ **Do not merge**. Just note in the log "PR #X is ready for human review" and finish. A merge into main = your person.

### Rule 6 — Idle

Nothing above matches → write "idle, nothing to do" in the log, update `last_tick_at`, exit. This is normal.

---

## Phase 4 — Execute one action

Invoke the chosen skill via the Skill tool. **Hand full control over to it** — it will do its own work. When control returns:

- If the inner skill returned success → go to phase 5
- If the inner skill got stuck / asked for confirmation / hit an error → go to phase 6 (escalate)
- If the inner skill ended **not clean** — `/review-loop` or `/codereview-dual-loop` exited through its Step 4, directly or as a `/sprint` / `/sprint-codex` task left ⚠️ blocked by it, or any operation is blocked by tick permissions → phase 6 with `outcome=blocked`. No branch finalization; the uncommitted changes stay for the person
- If you yourself did not get a response within a reasonable time (for example `/sprint` > 30 minutes) — escalate with the note "possibly stuck"

### After a successful `/sprint` — leave changes for the human

A task left ⚠️ blocked goes to phase 6. Otherwise go to phase 5, verify the prepared changes, show the exact files and proposed commit message, log `ready for review/commit`, notify TG if configured, and stop. Do not finalize the branch or create a PR.

---

## Phase 5 — Verify and log

### 5.1 Verify

Before saying "done" — invoke `superpowers:verification-before-completion` to check:
- The tests the skill promised → actually run and green?
- The files that should have changed → actually in the diff?
- Git status → the expected state?

If verification failed → fix or escalate. Do not write "done" if it is not verified.

### 5.2 Log

Append a line to `<docs.unsorted>/autopilot_log.md` (create it if it does not exist):

```markdown
## 2026-05-13 14:23 UTC — tick #N (TNN_xxx)
- **Решение**: Rule 3 → /sprint S08
- **Действие**: ran /sprint S08 → 3 tasks completed (T067, T068, T069)
- **Verify**: ✅ pytest passed, prepared files listed; human review pending
- **Branch**: <work_branch> @ <sha>
- **Tokens**: ~340k
- **Outcome**: ready for review/commit
- **Next**: human review and explicit commit/push approval
```

After verification, gather both `git diff --name-only` and `git ls-files --others --exclude-standard`. Report those files and a proposed commit message, status `ready for review/commit`, and actual test results; send this through `scripts/autopilot/tg_notify.sh` if configured. Do not treat a successful wrapper exit as proof that verification passed.

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
- **Артефакт**: <docs.unsorted>/autopilot_blocked_T072.md (детали)
```

### 6.2 TG ping (if configured)

If `AUTOPILOT_TG_BOT_TOKEN` and `AUTOPILOT_TG_CHAT_ID` are set in the env:

```bash
curl -fsSL -X POST "https://api.telegram.org/bot${AUTOPILOT_TG_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${AUTOPILOT_TG_CHAT_ID}" \
  --data-urlencode "text=🤖 Autopilot blocked — tick #N
T072: <детали>
Лог: <docs.unsorted>/autopilot_log.md"
```

**Important:** do not use `parse_mode=Markdown` or `MarkdownV2`. The message content may contain `_`, `*`, `[`, `]`, slashes (`/auto-pilot`, `--dry-run`) — Telegram will bounce it with a 400 parsing error. Plain text is safer, and informativeness does not suffer.

Use `--data-urlencode` (not `-d`) — otherwise special characters in `<детали>` may break the request.

If the env vars are absent (empty `AUTOPILOT_TG_BOT_TOKEN` or `AUTOPILOT_TG_CHAT_ID`) — note this in the log ("TG escalation skipped: no AUTOPILOT_TG_BOT_TOKEN/CHAT_ID"). Do not crash.

### 6.3 Set the pause flag

Prepend to `<handoff>`:
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
- Rule 3 → /sprint S08 → 3 задачи готовы к ревью (T067-T069)
- Статус: ready for review/commit
- Файлы: <конкретный список>
- Сообщение коммита: <предложение>
- Лог: <docs.unsorted>/autopilot_log.md
- Budget: 3/8 тиков, ~340k/5M токенов
```

On escalation:
```
🔴 tick #N BLOCKED
- Причина: <одна строка>
- Эскалировано: TG ping отправлен / TG ping skipped
- Пауза: ⛔ AUTOPILOT_PAUSE добавлено в HANDOFF
- Детали: <docs.unsorted>/autopilot_log.md
```

---

## What NOT to do (important)

1. **Do not create new SNN specs.** Specs are the person's domain (via `/spec-brainstorm`). You only decompose existing draft specs into tasks (Rule 4).
2. **Do not commit, push, merge, or create/merge any PR during a tick.** Leave the changes for explicit human approval in chat.
3. **Do not force-push / reset --hard / any destructive git operations.** Never. Even if review-loop suggests it.
4. **Do not interpret CLAUDE.md instructions expansively.** If `migrations/` is not in whitelist-paths — do not touch it even if the task formally requires it.
5. **Do not pick up tasks with `depends_on` not all in `<docs.tasks_done>`.** Be a stickler.
6. **Do not take two actions in one tick.** Decomposed a draft → STOP. Did /sprint → STOP. Prepared changes for review → STOP. The next tick will pick it up.
7. **Do not lie in the log.** If verify did not pass — write "outcome: partial/blocked". The log is for you on the following ticks.

---

## Links to other skills

| Skill | When the autopilot calls it |
|---|---|
| `/sprint S0X` | Rule 3 — the main working call |
| `<commands.spec_writer>` | Rule 4 — decomposition of a draft spec |
| `superpowers:verification-before-completion` | Phase 5.1 — always after an action |
| `superpowers:systematic-debugging` | If something strange failed in phase 4 and you want to triage before escalation |

**Never invoke directly:** `/codereview`, `/codereview-dual` (these are already inside the loop skills), `/codex-setup`, `/codex-toggle`, `/init_dev`, `skill-creator`.

---

## Cron mode

When invoked from a `CronCreate` job (not interactively):
- Do not ask the person questions (use `AskUserQuestion` only in --dry-run)
- If you find a situation that requires human judgment → escalate, do not block
- Notify TG when changes are ready for review/commit; idle ticks may stay silent.

Recommended schedule (UTC): `0 6,10,14,18 * * 1-5` — 4 ticks on weekdays, in MSK morning/midday/afternoon/evening.

---

## Future extensions (NOT for v1)

Do not implement, just keep in mind:
- Parallel ticks via worktrees
- Auto-merge into main under certain conditions (refactorings without logic)
- Self-learning from autopilot_log.md (analysis of what blocks often)
- Integration with `/sprint-codex` for waves of ≥2 tasks

For v1 — sequential ticks ending at human review/commit approval.
