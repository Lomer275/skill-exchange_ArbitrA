---
name: codereview-dual-loop
description: >
  A `codereview-dual → fix` loop until fully clean (only MEDIUM and LOW remain).
  Combines /codereview-dual (two lenses: Claude + Codex) and /review-loop (iterations
  until CRITICAL==0 AND HIGH==0). Use when the user says
  "/codereview-dual-loop", "двойной ревью до чистоты", "цикл двойного ревью",
  "dual review until clean", "две линзы до конца", "доведи dual-ревью до MEDIUM/LOW".
  A drop-in bundle of existing skills — does NOT replace them, works on top of them.
  Maximum 5 iterations. When Codex is unavailable — graceful fallback to a
  single /review-loop (Claude only) with an explicit marker.
---

# /codereview-dual-loop — Dual review loop until clean

A bundle of `/codereview-dual` + `/review-loop` in one explicit call. On each iteration — a parallel dual review (Claude + Codex), fixing only CRITICAL/HIGH in fast mode, repeating until clean or the limit is reached.

**It does NOT replace the existing skills** — `/codereview-dual` and `/review-loop` remain available as separate commands.

---

## Input

- `/codereview-dual-loop` — the task is determined automatically from `*HANDOFF.md` (the first 🟡).
- `/codereview-dual-loop T17` — an explicit task number.

If nothing is passed and there is no 🟡 in HANDOFF — ask the user.

---

## Stop criterion

**Stop:** `CRITICAL == 0 AND HIGH == 0`. MEDIUM and LOW do not block completion.

## Safety limit

Maximum **5 iterations**. After the 5th — abort with a warning and a list of the remaining blockers.

---

## Algorithm

### Step 0 — Routing checks (kill-switch + availability)

The same as in `/codereview-dual` (Step 0):

1. **Kill-switch.** Read `.claude/codex.json:enabled` + env `SUP_CODEX_ENABLED` (precedence matrix from CLAUDE.md). If disabled — graceful fallback: warn the user and delegate to the regular `/review-loop`:

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
Фиксы: быстрый режим (без подтверждения), только CRITICAL и HIGH
```

---

### Step 2 — Iteration (repeat until the stop criterion or the limit)

#### 2.1 — Run `/codereview-dual` directly

**IMPORTANT:** we call exactly `/codereview-dual`, **not** `/codereview` via routing. This is the very point of this skill — a forced dual without the routing fork.

```
Skill(skill="codereview-dual", args="T<NN>")
```

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
```

#### 2.3 — Check the stop criterion

- **If `CRITICAL == 0 AND HIGH == 0`** → Step 3 (success).
- **If iteration == 5 AND there are CRITICAL/HIGH** → Step 4 (limit reached).
- **Otherwise** → 2.4.

#### 2.4 — Run `/fix` in fast mode (CRITICAL and HIGH only)

The same constraints as in `/review-loop`:

- **CRITICAL and HIGH only** — MEDIUM and LOW are ignored.
- **Fast mode** — show the plan, do not wait for confirmation, execute immediately.
- **Order:** CRITICAL → HIGH.

```
Skill(skill="fix", args="T<NN> --fast --severity=CRITICAL,HIGH")
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

**Рекомендация:** код готов к принятию. Запусти `/accept T<NN>` для закрытия задачи.
```

---

### Step 4 — Final report (limit reached)

```markdown
## /codereview-dual-loop — Итог

**Задача:** T<NN> — <название>
**Итераций:** 5
**Статус:** ⚠️ Достигнут лимит — остались блокеры

### Оставшиеся блокеры (требуют ручного вмешательства):
| ID | Severity | Файл:строка | Описание | Источник |
|----|----------|-------------|----------|----------|
| RX | CRITICAL | ...         | ...      | [both]   |
| RY | HIGH     | ...         | ...      | [codex]  |

### Оставшиеся MEDIUM/LOW:
| ID | Severity | Описание |
|----|----------|----------|
| RZ | MEDIUM   | ...      |

**Рекомендация:** разреши блокеры вручную, затем запусти `/codereview-dual-loop` заново
или `/codereview-dual` для одиночной перепроверки.
```

---

## Rules

- **Routing check first.** When Codex is disabled/unavailable — graceful fallback to the regular `/review-loop` (not a crash).
- **Forced dual every iteration.** We call `/codereview-dual` directly — that is the point of the skill.
- **Fix only CRITICAL and HIGH** — do not touch MEDIUM/LOW.
- **Fast mode is mandatory** — show the plan, do not wait for confirmation.
- **Count iterations strictly** — an iteration = one full `codereview-dual + fix`.
- **If after the review CRITICAL/HIGH == 0** — go straight to the final report, without an extra fix run.
- **The 5-iteration limit is hard**, do not exceed it even on request.
- **Do not write git commit/push** — that is `/sup-push`.
- **Do not call this skill from `/sprint-codex`** — there, per rule R5 of spec S11, the sprint calls `/review-loop` to avoid a double dual-review. This skill is for manual use by the user.

---

## See also

- `/codereview-dual` — a single dual review without a loop.
- `/review-loop` — a loop with a routing choice of dual/single.
- `/fix` — applying fixes from the review table.
- `/codex-toggle` — kill-switch for the Claude × Codex bundle.
- Spec S11: [docs/2. SUP-specifications/S11_claude_codex_orchestration_done.md](../../docs/2.%20SUP-specifications/S11_claude_codex_orchestration_done.md)
