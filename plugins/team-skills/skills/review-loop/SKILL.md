---
name: review-loop
description: >
  Orchestrates a codereview → fix loop until fully clean (only MEDIUM and LOW remain).
  Use this skill when the user says "/review-loop", "гони ревью до чистоты",
  "прогони цикл ревью", "review until clean", "доведи до MEDIUM/LOW", "цикл ревью".
  The skill automatically repeats review and fixes until there are no
  CRITICAL and no HIGH findings left. Maximum 5 iterations.
---

# Review Loop Skill

A `codereview → fix` loop that repeats until there are no
CRITICAL and no HIGH findings left. Fixes run in fast mode (without waiting for confirmation).

---

## Stop criterion

**Stop:** `CRITICAL == 0 AND HIGH == 0`

All other findings (MEDIUM, LOW) are expected and do not block completion.

---

## Safety limit

Maximum **5 iterations**. If CRITICAL or HIGH findings remain after the 5th iteration,
the loop aborts with a warning.

---

## Execution algorithm

### Step 1 — Start

Tell the user:

```
## Review Loop — Старт

Запускаю цикл codereview → fix.
Стоп-критерий: CRITICAL == 0 AND HIGH == 0.
Максимум итераций: 5.
Фиксы применяются в быстром режиме (без ожидания подтверждения).
```

---

### Step 2 — Iteration (repeat until stop criterion or limit)

#### 2.1 — Run `/codereview`

Perform the full multi-phase review (phases A, B, C, D) according to the `codereview` skill.
Obtain the findings table with severity.

#### 2.2 — Count CRITICAL and HIGH

From the findings table:
- Count the number of `CRITICAL` findings
- Count the number of `HIGH` findings

Output the interim status:

```
### Итерация N — Результат ревью
CRITICAL: X | HIGH: Y | MEDIUM: Z | LOW: W
```

#### 2.3 — Check the stop criterion

**If `CRITICAL == 0 AND HIGH == 0`** → go to Step 3 (final report).

**If the limit is reached (iteration == 5) and CRITICAL/HIGH still remain** → go to Step 4 (limit).

**Otherwise** → go to 2.4.

#### 2.4 — Run `/fix` in fast mode (CRITICAL and HIGH only)

Apply fixes according to the `fix` skill with the following constraints:

- **CRITICAL and HIGH only** — skip MEDIUM and LOW
- **Fast mode** — show the fix plan, but do not wait for user confirmation, execute right away
- **Order:** CRITICAL → HIGH

After the fixes are complete, return to Step 2 (next iteration).

---

### Step 3 — Final report (success)

```
## Review Loop — Итог

**Итераций:** N
**Статус:** ✅ Чисто (только MEDIUM и LOW)

### Оставшиеся находки (MEDIUM и LOW — ожидаемо):
| ID | Severity | Описание |
|----|----------|----------|
| RX | MEDIUM   | ...      |
| RY | LOW      | ...      |

**Рекомендация:** Код готов к принятию. Запусти /accept для закрытия задачи.
```

---

### Step 4 — Final report (limit exhausted)

```
## Review Loop — Итог

**Итераций:** 5
**Статус:** ⚠️ Достигнут лимит

### Оставшиеся блокеры (требуют ручного вмешательства):
| ID | Severity | Файл:строка | Описание |
|----|----------|-------------|----------|
| RX | CRITICAL | ...         | ...      |
| RY | HIGH     | ...         | ...      |

### Оставшиеся находки (MEDIUM и LOW — ожидаемо):
| ID | Severity | Описание |
|----|----------|----------|
| RZ | MEDIUM   | ...      |

**Рекомендация:** Блокеры не удалось устранить автоматически за 5 итераций.
Реши их вручную, затем запусти /review-loop снова или /codereview для проверки.
```

---

## Rules

- **Fix only CRITICAL and HIGH** in each iteration — do not touch MEDIUM and LOW
- **Fast mode is mandatory** — show the plan, do not wait for confirmation
- **Count iterations strictly** — one iteration = one full review + fix cycle
- **Do not stop after review** without checking the stop criterion
- **If CRITICAL/HIGH == 0 after review** — go straight to the final report, without an extra fix run
- **5-iteration limit** — a hard constraint, do not exceed even if the user asks
