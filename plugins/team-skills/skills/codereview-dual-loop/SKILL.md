---
name: codereview-dual-loop
description: >
  A `codereview-dual → fix` loop until fully clean (only MEDIUM and LOW remain).
  Combines /codereview-dual (two lenses: Claude + Codex) and /review-loop (iterations
  until CRITICAL==0 AND HIGH==0). Use when the user says
  "/codereview-dual-loop", "двойной ревью до чистоты", "цикл двойного ревью",
  "dual review until clean", "две линзы до конца", "доведи dual-ревью до MEDIUM/LOW".
  A drop-in bundle of existing skills — does NOT replace them, works on top of them.
  Maximum 5 iterations; stops earlier on a plateau. When Codex is unavailable — graceful fallback to a
  single /review-loop (Claude only) with an explicit marker.
  If the project or the user has its own `codereview-dual-loop` skill, that one takes precedence — use this one only when the user typed `/team-skills:codereview-dual-loop` or no such skill exists.
---

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:codereview-dual-loop` and a skill named `codereview-dual-loop` exists in the project (`.claude/skills/codereview-dual-loop/SKILL.md`) or in the user's skills (`~/.claude/skills/codereview-dual-loop/SKILL.md`), stop: tell the user that their own `/codereview-dual-loop` takes precedence, and do nothing else.

## Codex model and effort (mandatory)

Resolve each value independently: explicit invocation argument (`model=`, `effort=`) →
`.claude/codex.json` → built-in `gpt-6-luna` / `medium`. Never use
`~/.codex/config.toml` for model selection. Pass both resolved values on every
worker call and model launch; probes, warm-up and smoke tests use the resolved
model with effort `low`. Cache availability by model, probe effort and engine (TTL 1h);
a different model requires a fresh probe. Log/report the model and effort actually sent.

Luna: `gpt-6-luna`, effort `low|medium|high|xhigh|max` (no `ultra`).
Sol: `gpt-6.1-sol`; Astra: `gpt-6-astra` (most expensive).
A caller choosing a stronger model must explain why in one line to the user.
Reject unsupported model/effort combinations; never silently drop or lower effort.

## Project paths

No project profile is required. If `.claude/team-skills.json` exists, read only needed keys `handoff`, `docs.guides`.
Missing profile/key → skip that project-document step and report it; never guess a prefix or use project-specific fallback paths.
All document paths are repository-relative. Resolve HANDOFF from `handoff` and GUIDES_DIR from `docs.guides`.

Resolve the push skill from `commands.push` in `.claude/team-skills.json`; if the file/key is absent use `/team-skills:safe-push` (the only command default). References to `<push-command>` below mean this resolved command.

# /codereview-dual-loop — Dual review loop until clean

A bundle of `/codereview-dual` + `/review-loop` in one explicit call. On each iteration — a parallel dual review (Claude + Codex), fixing only CRITICAL/HIGH in fast mode, repeating until clean, a plateau or the limit is reached.

**It does NOT replace the existing skills** — `/codereview-dual` and `/review-loop` remain available as separate commands.

---

## Input

- `/codereview-dual-loop` — the task is determined automatically from the profile `handoff` document (if configured) (the first 🟡).
- `/codereview-dual-loop T17` — an explicit task number.

If no task was passed, use the configured handoff only if available. Otherwise skip that lookup with a note and ask for the task/file scope.

---

## Stop criterion

**Stop:** `CRITICAL == 0 AND HIGH == 0`. MEDIUM and LOW do not block completion; `OLD-` rows (older bugs on main, outside the change) are not counted anywhere in this loop.

## Safety limit

Maximum **5 iterations**. After the 5th — abort with a warning and a list of the remaining blockers.

**Plateau — stop early** (the same rule as `/review-loop`; change both together). From iteration 2 on, compare the review with the previous one:

- **No progress** = CRITICAL+HIGH did not go down — only the count decides. `K` — no-progress iterations in a row; an iteration where the count went down resets it to 0.
- **The same finding** = the same file, the same enclosing function (no function → within ±5 lines) and the same defect. Never match by ID — every review renumbers. In doubt, it is a new finding.

Stop right away, Step 4, when **K == 2** or when **one CRITICAL/HIGH finding is in its third review in a row** (it survived two fix rounds). If the reviewers changed between two iterations — the `[fallback: claude-only …]` marker appeared or went away — the reviews are not comparable: set K to 0 and restart every finding's «reviews in a row» count at 1. The iteration number and the cap of 5 are not reset; the plateau rule can only stop the loop earlier.

---

## Algorithm

### Step 0 — Routing checks (kill-switch + availability)

The same as in `/codereview-dual` (Step 0):

1. **Kill-switch.** Read `.claude/codex.json:enabled` + env `SUP_CODEX_ENABLED` (recognized env value wins, otherwise file). If disabled — graceful fallback: warn the user and delegate to the regular `/review-loop`:

   ```
   ⚠️ Codex отключён. Делаю одиночный /review-loop (только Claude).
   Включить связку — /codex-toggle on.
   ```

   STOP here, handing control to `/review-loop`.

2. **Availability cache.** Fresh check if the cache is stale (TTL 1 hour). On `available=false` — the same fallback as above.

When both are ✅ — continue the dual-loop.

---

### Step 1 — Start

Tell the user:

```
## /codereview-dual-loop — Старт

Задача: T<NN> — <название>
Режим: dual (Claude + Codex параллельно) × итерации до чистоты
Стоп-критерий: CRITICAL == 0 AND HIGH == 0
Максимум итераций: 5
Досрочный стоп: две итерации подряд без снижения CRITICAL+HIGH или находка, пережившая два раунда фиксов
Фиксы: быстрый режим (без подтверждения), только CRITICAL и HIGH
```

---

### Step 2 — Iteration (repeat until the stop criterion, a plateau or the limit)

#### 2.1 — Run `/codereview-dual` directly

**IMPORTANT:** we call exactly `/codereview-dual`, **not** `/codereview` via routing. This is the very point of this skill — a forced dual without the routing fork.

```
Skill(skill="codereview-dual", args="T<NN> model=<resolved-model> effort=<resolved-effort>")
```

From iteration 2 on, add every file this loop's `/fix` runs changed outside the task's list (each fix in a `/fix` plan names its «**Файл:**»): `args="T<NN> +files: <файл> <файл>"`. Those files are part of the change (`/codereview` Step 0).

Get the findings table with a "Source" column (`[both]`/`[claude]`/`[codex]`).

#### 2.2 — Count CRITICAL and HIGH

From the table:
- `CRITICAL` — the number of findings of this severity.
- `HIGH` — the number of findings of this severity.
- Additionally: `[both]`, `[claude]`, `[codex]`, `[severity-disputed]`.

Interim status:

```
### Итерация N — Результат dual-ревью
CRITICAL: X | HIGH: Y | MEDIUM: Z | LOW: W
Источники: [both]: A | [claude]: B | [codex]: C
Расхождения severity: D [severity-disputed]
Открытые CRITICAL/HIGH: <файл:функция — дефект; нет функции — файл:строка — дефект>; …
Прогресс к итерации N-1: CRITICAL+HIGH P → Q; повторяются: <файл:функция — ревью подряд, или —>; без снижения подряд: K
```

«Открытые» is the ledger the next iteration compares against — print it every time. The «Прогресс» line starts at iteration 2 (see «Plateau» in Safety limit).

#### 2.3 — Check the stop criterion

- **If `CRITICAL == 0 AND HIGH == 0`** → Step 3 (success).
- **If iteration == 5 AND there are CRITICAL/HIGH** → Step 4 (limit reached) — even if a plateau condition holds too; fill «Что возвращалось» anyway.
- **If K == 2** (see «Plateau») → Step 4 (plateau).
- **If a CRITICAL/HIGH finding is in its third review in a row** → Step 4 (survived two fix rounds).
- **Otherwise** → 2.4.

#### 2.4 — Run `/fix` in fast mode (CRITICAL and HIGH only)

The same constraints as in `/review-loop`:

- **CRITICAL and HIGH only** — MEDIUM and LOW are ignored.
- **Fast mode** — show the plan, do not wait for confirmation, execute immediately.
- **Order:** CRITICAL → HIGH.

```
Skill(skill="fix", args="T<NN> model=<resolved-model> effort=<resolved-effort> --fast --severity=CRITICAL,HIGH")
```

After the fixes are done — return to Step 2 (the next iteration).

---

### Step 3 — Final report (success)

```markdown
## /codereview-dual-loop — Итог

**Задача:** T<NN> — <название>
**Итераций:** N
**Статус:** ✅ Чисто (только MEDIUM и LOW)

### Покрытие dual-режима за все итерации:
- [both]: <число суммарно>
- [claude]: <число>
- [codex]: <число>
- [severity-disputed]: <число>

### Оставшиеся находки (MEDIUM и LOW — ожидаемо):
| ID | Severity | Описание | Источник |
|----|----------|----------|----------|
| RX | MEDIUM   | ...      | [both]   |
| RY | LOW      | ...      | [codex]  |

**Старые баги main (OLD-, вне изменения, в счёт не идут):** <ID — файл:строка — severity — описание>; … или «—». Чинить отдельно, в worktree от origin/main.

**Рекомендация:** код готов к принятию. Запусти `/accept T<NN>` для закрытия задачи.
```

---

### Step 4 — Final report (limit reached or plateau)

```markdown
## /codereview-dual-loop — Итог

**Задача:** T<NN> — <название>
**Итераций:** N
**Статус:** ⚠️ Достигнут лимит (5) — остались блокеры | ⚠️ Плато — две итерации подряд без снижения CRITICAL+HIGH | ⚠️ Находка пережила два раунда фиксов

### Оставшиеся блокеры (требуют ручного вмешательства):
| ID | Severity | Файл:строка | Описание | Источник |
|----|----------|-------------|----------|----------|
| RX | CRITICAL | ...         | ...      | [both]   |
| RY | HIGH     | ...         | ...      | [codex]  |

### Что возвращалось
| Находка (файл:функция — дефект) | В каких ревью | Что меняли фиксы |
|---------------------------------|---------------|------------------|
| ...                             | 1, 2, 3       | итерация 1: …; итерация 2: … |

### Оставшиеся MEDIUM/LOW:
| ID | Severity | Описание |
|----|----------|----------|
| RZ | MEDIUM   | ...      |

**Старые баги main (OLD-, вне изменения, в счёт не идут):** <ID — файл:строка — severity — описание>; … или «—». Чинить отдельно, в worktree от origin/main.

**Рекомендация:** <по статусу, см. ниже>
```

«Что возвращалось» lists every CRITICAL/HIGH finding seen in two or more reviews of this run, in a row or with a gap, and what each fix round changed in it — that is what the human needs in order to decide; nothing came back → «—». The recommendation follows the status:
- limit → «Разреши блокеры вручную, затем `/codereview-dual-loop` заново или `/codereview-dual` для одиночной перепроверки.»
- plateau → «Фиксы ходят по кругу: две итерации CRITICAL+HIGH не снижались. Нужен другой подход — разбери «Что возвращалось», прежде чем запускать цикл снова.»
- survived two fix rounds → «Находка пережила два раунда фиксов: вероятно, причина в плане неверна или сама находка ложная. Перепроверь её, затем реши вручную.»

A Step 4 exit is **not clean**: whoever called this loop must not go on to `/accept` or `<push-command>` for this task.

---

## Rules

- **Routing check first.** When Codex is disabled/unavailable — graceful fallback to the regular `/review-loop` (not a crash).
- **Forced dual every iteration.** We call `/codereview-dual` directly — that is the point of the skill.
- **Fix only CRITICAL and HIGH** — do not touch MEDIUM/LOW.
- **Fast mode is mandatory** — show the plan, do not wait for confirmation.
- **Count iterations strictly** — an iteration = one full `codereview-dual + fix`.
- **If after the review CRITICAL/HIGH == 0** — go straight to the final report, without an extra fix run.
- **The 5-iteration limit is hard**, do not exceed it even on request; the plateau rule may stop the loop earlier, never later.
- **`OLD-` rows don't count** — older bugs on main are outside the change: not in the stop criterion, not in K, not fixed by the loop. They are never copied into the blocker or MEDIUM/LOW tables; the final report lists the last review's `OLD-` rows in the «Старые баги main» line.
- **Do not write git commit/push** — that is `<push-command>`.
- **Do not call this skill from `/sprint-codex`** — there, per spec S11 Phase 4 (rule R5 in `/sprint-codex`), the sprint calls `/review-loop` to avoid a double dual-review. This skill is for manual use by the user.

---

## See also

- `/codereview-dual` — a single dual review without a loop.
- `/review-loop` — the same loop with a single Claude review (`/codereview`).
- `/fix` — applying fixes from the review table.
- `/codex-toggle` — kill-switch for the Claude × Codex bundle.
- Spec S11: спецификация S11 «Claude × Codex orchestration» в документации вашего проекта
