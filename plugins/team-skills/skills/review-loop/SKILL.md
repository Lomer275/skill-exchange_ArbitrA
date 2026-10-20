---
name: review-loop
description: >
  Orchestrates a codereview → fix loop until fully clean (only MEDIUM and LOW remain).
  Use this skill when the user says "/review-loop", "гони ревью до чистоты",
  "прогони цикл ревью", "review until clean", "доведи до MEDIUM/LOW", "цикл ревью".
  The skill automatically repeats review and fixes until there are no
  CRITICAL and no HIGH findings left. Maximum 5 iterations; stops earlier on a plateau.
---

# Review Loop Skill

A `codereview → fix` loop that repeats until there are no
CRITICAL and no HIGH findings left, at most 5 times, and stops earlier when the fixes go in
circles. Fixes run in fast mode (without waiting for confirmation).

---

## Stop criterion

**Stop:** `CRITICAL == 0 AND HIGH == 0`

All other findings (MEDIUM, LOW) are expected and do not block completion.

---

## Safety limit

Maximum **5 iterations**. If CRITICAL or HIGH findings remain after the 5th iteration,
the loop aborts with a warning.

**Plateau — stop early.** From iteration 2 on, compare the review with the previous one.
`OLD-` rows (older bugs on main, outside the change) are not counted anywhere in this loop.

- **No progress** = CRITICAL+HIGH did not go down. Only the count decides: a fix that
  removes two findings and uncovers one new one is progress. `K` — no-progress iterations in
  a row; an iteration where the count went down resets it to 0.
- **The same finding** = the same file, the same enclosing function (no function → within
  ±5 lines) and the same defect. Never match by ID — every review renumbers. In doubt, it is a
  new finding: a wrong match must not stop the loop.

Stop right away and go to Step 4 when **K == 2** (two iterations in a row without the count
going down), or when **one CRITICAL/HIGH finding is in its third review in a row** — it
survived two fix rounds. More rounds only burn tokens. The cap of 5 stays; the plateau rule
can only stop the loop earlier.

---

## Execution algorithm

### Step 1 — Start

Tell the user:

```
## Review Loop — Старт

Запускаю цикл codereview → fix.
Стоп-критерий: CRITICAL == 0 AND HIGH == 0.
Максимум итераций: 5.
Досрочный стоп: две итерации подряд без снижения CRITICAL+HIGH или находка, пережившая два раунда фиксов.
Фиксы применяются в быстром режиме (без ожидания подтверждения).
```

---

### Step 2 — Iteration (repeat until stop criterion, plateau or limit)

#### 2.1 — Run `/codereview`

Perform the full multi-phase review (phases A, B, C, D) according to the `codereview` skill.
Obtain the findings table with severity. From iteration 2 on, name to the review every file this
loop's `/fix` runs changed outside the task's list (each fix in a `/fix` plan names its «**Файл:**»): those files
are part of the change (`/codereview` Step 0).

#### 2.2 — Count CRITICAL and HIGH

From the findings table:
- Count the number of `CRITICAL` findings
- Count the number of `HIGH` findings

Output the interim status:

```
### Итерация N — Результат ревью
CRITICAL: X | HIGH: Y | MEDIUM: Z | LOW: W
Открытые CRITICAL/HIGH: <файл:функция — дефект; нет функции — файл:строка — дефект>; …
Прогресс к итерации N-1: CRITICAL+HIGH P → Q; повторяются: <файл:функция — ревью подряд, или —>; без снижения подряд: K
```

«Открытые» is the ledger the next iteration compares against — print it every time. The
«Прогресс» line starts at iteration 2 (see «Plateau» above).

#### 2.3 — Check the stop criterion

**If `CRITICAL == 0 AND HIGH == 0`** → go to Step 3 (final report).

**If the limit is reached (iteration == 5) and CRITICAL/HIGH still remain** → go to Step 4 (limit) — even if a plateau condition holds too; fill «Что возвращалось» anyway.

**If K == 2** (see «Plateau») → go to Step 4 (plateau).

**If a CRITICAL/HIGH finding is in its third review in a row** → go to Step 4 (survived two fix rounds).

**Otherwise** → go to 2.4.

#### 2.4 — Run `/fix` in fast mode (CRITICAL and HIGH only)

Apply fixes according to the `fix` skill (`/fix --fast --severity=CRITICAL,HIGH`) with the following constraints:

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

**Старые баги main (OLD-, вне изменения, в счёт не идут):** <ID — файл:строка — severity — описание>; … или «—». Чинить отдельно, в worktree от origin/main.

**Рекомендация:** Код готов к принятию. Запусти /accept для закрытия задачи.
```

---

### Step 4 — Final report (limit exhausted or plateau)

```
## Review Loop — Итог

**Итераций:** N
**Статус:** ⚠️ Достигнут лимит (5) | ⚠️ Плато — две итерации подряд без снижения CRITICAL+HIGH | ⚠️ Находка пережила два раунда фиксов

### Оставшиеся блокеры (требуют ручного вмешательства):
| ID | Severity | Файл:строка | Описание |
|----|----------|-------------|----------|
| RX | CRITICAL | ...         | ...      |
| RY | HIGH     | ...         | ...      |

### Что возвращалось
| Находка (файл:функция — дефект) | В каких ревью | Что меняли фиксы |
|---------------------------------|---------------|------------------|
| ...                             | 1, 2, 3       | итерация 1: …; итерация 2: … |

### Оставшиеся находки (MEDIUM и LOW — ожидаемо):
| ID | Severity | Описание |
|----|----------|----------|
| RZ | MEDIUM   | ...      |

**Старые баги main (OLD-, вне изменения, в счёт не идут):** <ID — файл:строка — severity — описание>; … или «—». Чинить отдельно, в worktree от origin/main.

**Рекомендация:** <по статусу, см. ниже>
```

«Что возвращалось» lists every CRITICAL/HIGH finding seen in two or more reviews of this run,
in a row or with a gap, and what each fix round changed in it — that is what the human needs in order to decide;
nothing came back → «—». The recommendation follows the status:
- limit → «Блокеры не устранены за 5 итераций. Реши их вручную, затем /review-loop или /codereview.»
- plateau → «Фиксы ходят по кругу: две итерации CRITICAL+HIGH не снижались. Нужен другой подход — разбери «Что возвращалось», прежде чем запускать цикл снова.»
- survived two fix rounds → «Находка пережила два раунда фиксов: вероятно, причина в плане неверна или сама находка ложная. Перепроверь её, затем реши вручную.»

A Step 4 exit is **not clean**. A caller (`/sprint`, `/sprint-codex`, the autopilot) must not
go on to `/accept` or `/sup-push` for this work: it shows the blockers and stops.

---

## Rules

- **Fix only CRITICAL and HIGH** in each iteration — do not touch MEDIUM and LOW
- **Fast mode is mandatory** — show the plan, do not wait for confirmation
- **Count iterations strictly** — one iteration = one full review + fix cycle
- **Do not stop after review** without checking the stop criterion
- **If CRITICAL/HIGH == 0 after review** — go straight to the final report, without an extra fix run
- **5-iteration limit** — a hard constraint, do not exceed even if the user asks; the plateau rule may stop the loop earlier, never later
- **`OLD-` rows don't count** — older bugs on main are outside the change: not in the stop criterion, not in K, not fixed by the loop. They are never copied into the blocker or MEDIUM/LOW tables; the final report lists the last review's `OLD-` rows in the «Старые баги main» line
