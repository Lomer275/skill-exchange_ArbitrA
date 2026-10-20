---
name: codereview-dual
description: >
  Dual independent code review: runs a Codex reviewer in the background in parallel
  with its own phases (acceptance criteria + adversarial), then merges the findings
  into a single severity-ranked table with [both]/[claude]/[codex] markers. Output
  is compatible with /fix and /review-loop. Use when the user says
  "/codereview-dual", "двойной ревью", "ревью с codex", "две линзы", "ревью с кодексом",
  or when routing decides on dual mode (Codex available and enabled). When Codex is
  unavailable — graceful fallback to single-review with an explicit marker. Part of spec S11, Phase 3.
---

# /codereview-dual — Parallel dual code review with Codex

Runs a Codex reviewer and a Claude reviewer in parallel, then merges the findings into one report. A drop-in replacement for `/codereview` — output is compatible with `/fix` and `/review-loop`.

---

## Input

- `/codereview-dual` — the task is determined automatically from `*HANDOFF.md` (the first 🟡)
- `/codereview-dual T17` — an explicit task number
- `/codereview-dual T17 +files: a.py b.py` — from a review loop: files the loop's `/fix` runs changed outside the task's list; they are part of the change (Step 1 item 4)

If nothing is passed and there is no 🟡 in HANDOFF — ask the user.

---

## Algorithm

### Step 0 — Pre-flight (kill-switch, availability, tree)

#### 0.1 — Kill-switch

Read `.claude/codex.json`:

```bash
ENABLED=$(jq -r '.enabled' .claude/codex.json)
ENV_VAL="${SUP_CODEX_ENABLED:-}"
case "$ENV_VAL" in
  true|1|yes)   FINAL=true ;;
  false|0|no)   FINAL=false ;;
  "")           FINAL=$ENABLED ;;
  *)            FINAL=$ENABLED ;;
esac
```

If `FINAL=false` — refuse to start:

```
❌ Codex is disabled in .claude/codex.json (or via SUP_CODEX_ENABLED).
Use /codereview directly or enable Codex via /codex-toggle on.
```

STOP. Don't continue.

#### 0.2 — Availability cache

Read `availability_cache` from `.claude/codex.json`:

- Get the current Claude Code session_id (via the `CLAUDE_SESSION_ID` env variable or metadata; if unavailable — generate a UUID per run).
- Compare `availability_cache.session_id` and `checked_at`:
  - session_id matches AND `checked_at` ≤ 1 hour ago → use the cached `available`.
  - otherwise → run the check: `codex --version && timeout 10 codex exec --skip-git-repo-check "echo ok"`. Update `availability_cache`. This `codex exec` also warms the shared app-server daemon and refreshes the OAuth token serially, so a subsequent worker launch never triggers a cold-start refresh race.
- **Min CLI version:** require `codex --version` ≥ **0.143.0** (adds the cross-process OAuth `refresh.lock`, [openai/codex#10332](https://github.com/openai/codex/issues/10332)); on older CLIs concurrent Codex work is unstable — hint the user to run `npm i -g @openai/codex@latest`.

If `available=false` — graceful fallback to single-review: skip Steps 2 and 4, run 0.3 and Steps 1 and 3, then 5.0 and 5b (Claude rows only, codex counts 0).

#### 0.3 — Which tree is under review

Read `.claude/skills/codereview/SKILL.md` now. Its Step 0 (the tree check, what counts as the change, sorting findings against main) and its Phases B and D are the rules this skill applies; they are not repeated here. Run its Step 0 commands from the repo root.

The Codex reviewer reads the same tree and is not told it is behind main or dirty, so Step 5.0 sorts `[codex]` rows exactly like Claude's. The tree line goes into the report (Steps 6 and 7).

---

### Step 1 — Gather context

1. Find the task file: glob `docs/3. <ПРЕФИКС>-tasks/T<NN>_*.md` (or from HANDOFF).
2. Read the task file: acceptance criteria, description, affected files.
3. Determine the specification path (from the `**Спецификация:**` line).
4. Read the change — the files the task names plus any `+files:` from the args, compared with the fork point as in `/codereview` Step 0 — and the code around it.

If the code is not provided and not specified in the task — ask the user to attach it.

---

### Step 2 — Parallel start of the Codex reviewer

In a single message (without delays):

```
Skill(skill="codex-worker", args="role=reviewer task_file=docs/3. <ПРЕФИКС>-tasks/T<NN>_<name>.md spec_file=docs/2. <ПРЕФИКС>-specifications/S<NN>_<name>.md scope=read-only lens=correctness,edge-cases,risks timeout_min=5 task_id=T<NN>")
```

**Codex lens:** `correctness`, `edge-cases`, `risks` — **different from Claude's**, to provide a complementary signal.

Save the returned `output_file` and `task_id`.

To chat:
```
🚀 Codex reviewer launched in the background (lens: correctness/edge-cases/risks).
In parallel I'm running my own phases (A: acceptance criteria, B: adversarial).
```

---

### Step 3 — Own phases (in parallel over time)

Right away (without waiting for Codex), run the phases from `/codereview`:

- **Phase A — acceptance criteria:** for each DoD item of the task — find it in the code, verdict ✅/❌/⚠️.
- **Phase B — adversarial:** "How will this code break?" — all of `/codereview` Phase B, including its two groups that apply only to the lines the change adds or modifies, with their triggers and exceptions as written there: **silent failures** (category `correctness`) and **LLM boundary** (category `security`).
- **Phase C — user walkthrough:** 3-5 scenarios (happy/empty/error/edge/concurrent).
- **Phase D — architectural fit:** as in `/codereview` Phase D — project patterns, the `CLAUDE.md` of every touched top-level directory and every env flag the change touches, both looked up on main.

Build your own findings table with columns: `ID, Severity, Фаза, Файл:строка, Категория, Описание, Сценарий отказа, Рекомендация`.

**«Сценарий отказа» is mandatory**: concrete input or state → the wrong result or the crash it produces. «Дано пустой `contact_id`; когда приходит вебхук; тогда `KeyError` и событие теряется» is a scenario. «Возможна гонка», «стоит проверить на None» are not — either find the input that breaks it, or drop the finding. The same applies to `Файл:строка`: a finding that cannot be pinned to a line is not shown.

**Categories** (for matching): `acceptance-criteria`, `correctness`, `security`, `performance`, `style`, `dead-code`, `architecture`, `edge-case`.

---

### Step 4 — Collect Codex output (poll)

After finishing your own phases — `Read(output_file)` from codex-worker.

- File exists and is non-empty → parse the Codex table.
- File is empty → poll every 2-3 sec until it becomes non-empty, limit — `timeout_min` (5 min).
- Codex crashed / `status: timeout|error` → fallback (Step 5).

**Parsing the Codex output:** it is free text in the codex-worker reviewer format — top findings with severity, `файл:строка`, a failure scenario and a recommended fix — not a table. Extract each finding into the columns of Step 3, `Фаза` = `—`; output you cannot split into findings → fallback. The Codex reviewer is asked for a failure scenario per finding (codex-worker reviewer prompt); a Codex finding without one is treated exactly like a Claude finding without one — dropped in Step 5.

---

### Step 5 — Merge findings (or fallback)

#### 5.0 — Drop unverifiable findings and snapshot phantoms (before matching, and before the 5b fallback)

From both sources, remove every finding that has **no `файл:строка`** (a file alone, a function name, «в модуле X» do not count) **or no failure scenario** (empty, or a restatement of the description without an input and a wrong outcome). Count them per source. They never reach the table, `/fix` or the owner — an unverifiable finding costs a fix round and teaches nothing.

Then sort what is left by `/codereview` Step 0, both sources alike. Cluster first: findings of the two sources on the same file with overlapping lines (as `is_same` in 5a, without the category) are sorted once, and every row of the cluster gets that outcome. A real bug that main has too goes to its own table «Старые баги main (вне изменения)» with an `OLD-<n>` ID — one row per cluster, with the cluster's sources as «Источник» (`[both]` / `[claude]` / `[codex]`) and its highest severity. A phantom of the snapshot is dropped and counted per source; if `scripts/staff/metrics.py` exists, log each one as `/fix` Step 5b does — `outcome: rejected`, the summary starting «фантом устаревшего дерева:», `source` its own.

Under the merged table, one line, always present (zero included), and a second one when the findings were sorted against main:

```
Отброшено без файл:строка или сценария: N (claude: a, codex: b)
Отброшено как фантом устаревшего дерева: K (claude: a, codex: b)
```

#### 5a — Full merge (Codex returned a result)

**Matching algorithm (R11):**

Codex findings carry no category. Assign one to each before matching, from its failure scenario: an unusual or empty input → `edge-case`; a leak, an injection, access to someone else's data → `security`; a design problem → `architecture`; any other wrong result → `correctness`. Assign once and never change it after matching.

For each finding from both sources — compare it pairwise with the findings of the other source:

```python
def is_same(c, x):
    return (
        c.file_path == x.file_path
        and ranges_overlap(c.line_range, x.line_range)  # max(s1,s2) <= min(e1,e2)
        and c.category == x.category
    )
```

If matched:
- Description = the more informative one (longer in characters when informativeness is equal).
- Marker = `[both]`.
- **Severity disagreement (R13):**
  - If the severities differ — take the maximum (CRITICAL > HIGH > MEDIUM > LOW).
  - The marker is extended: `[both, severity=max(claude=X, codex=Y)→Z]`.
  - On a radical disagreement (CRITICAL↔LOW) — an additional marker `[severity-disputed]`.

Unmatched ones — `[claude]` or `[codex]` depending on the source.

#### 5b — Fallback (Codex unavailable)

If `availability_cache.available=false`, Codex returned `status: timeout|error`, or its output could not be split into findings (Step 4; reason «unparseable output»):

To chat:
```
⚠️ Codex unavailable (<reason>). Doing a single-review (Claude only).
```

Use only your own findings. The marker `[fallback: claude-only, Codex unavailable: <reason>]` goes at the end of the «Ревьюеры» line in Step 6 and of the «Sources» line in Step 7; the loops look for it there.

---

### Step 6 — Write to the task file

In the task file (`docs/3. <ПРЕФИКС>-tasks/T<NN>_*.md`) add/update the section:

```markdown
## Code Review (dual)

**Дата:** YYYY-MM-DD
**Дерево:** <ветка>, <pwd>, позади main: <n>, впереди: <m>, грязных вне изменения: <d>
**Ревьюеры:** Claude (фазы A/B/C/D), Codex (correctness/edge-cases/risks)   ← при фолбэке вместо Codex: [fallback: claude-only, Codex unavailable: <причина>]
**Найдено:** N CRITICAL, M HIGH, K MEDIUM, L LOW
**Расхождения:** X [severity-disputed]

| ID | Severity | Фаза | Файл:строка | Описание | Сценарий отказа | Рекомендация | Источник |
|----|----------|------|-------------|----------|-----------------|--------------|----------|
| R1 | CRITICAL | B | ... | ... | дано …; когда …; тогда … | ... | [both] |
| R2 | HIGH | A | ... | ... | ... | ... | [claude] |
| R3 | HIGH | B | ... | ... | ... | ... | [codex] |
| R4 | MEDIUM | C | ... | ... | ... | ... | [both, severity=max(claude=LOW, codex=MEDIUM)→MEDIUM] |

Отброшено без файл:строка или сценария: N (claude: a, codex: b)
Отброшено как фантом устаревшего дерева: K (claude: a, codex: b)

### Старые баги main (вне изменения)

| ID | Severity | Файл:строка на main | Описание | Сценарий отказа | Рекомендация | Источник |
|----|----------|---------------------|----------|-----------------|--------------|----------|
| OLD-1 | MEDIUM | ... | ... | дано …; когда …; тогда … | ... | [codex] |
```

The phantom line appears only when 5.0 sorted against main, the `OLD-` table only when it has at least one row. `OLD-` rows count neither in «Найдено» nor in the «Next step» decision; `/fix` and the loops skip them unless the user names them. The Step 0 marks «есть только в ветке» and «не проверено на main» go at the start of the row's «Описание». If the fetch in Step 0 failed, the «Дерево» line here and the «Tree» line in Step 7 end with «origin/main не обновлён».

`/fix` turns each «Сценарий отказа» into an example of its brief and logs the finding's outcome (`accepted` / `rejected`) with the «Источник» value as `source`.

If the section already existed — add a new one (don't overwrite old reviews), marking it with a date.

---

### Step 7 — Final report to chat

```markdown
## /codereview-dual — Done

**Task:** T<NN> — <name>
**Tree:** <branch>, <pwd> — behind origin/main: <b>, ahead: <a>, dirty outside the change: <d>
**Found:** N CRITICAL, M HIGH, K MEDIUM, L LOW
**Sources:** [both]: <count> | [claude]: <count> | [codex]: <count>   ← on fallback, the marker at the end
**Severity disagreements:** <count> [severity-disputed]
**Dropped (no файл:строка or scenario):** <count> (claude: a, codex: b)
**Dropped as snapshot phantoms:** <count> (claude: a, codex: b) — only when sorted against main
**Older bugs on main:** <count> `OLD-` rows, not counted above — fix them in a worktree off origin/main

**Task file updated:** docs/3. <ПРЕФИКС>-tasks/T<NN>_*.md (section `## Code Review (dual)`)

**Next step:**
- If there are CRITICAL/HIGH — run `/fix` or `/review-loop`.
- If only MEDIUM/LOW — you can `/accept`.
```

---

## Rules

- **Routing is the first step.** Don't start without the kill-switch + availability check.
- **Parallelism over time, not concurrency.** Codex starts in the background via `Skill("codex-worker", ...)`, Claude runs its own phases in parallel, then reads the Codex output.
- **The Codex lens differs from Claude's.** Don't duplicate coverage — Claude takes criteria+adversarial, Codex — correctness+edge-cases+risks.
- **Severity max on disagreement.** Adversarially — pick the worst case.
- **Output is compatible with /fix and /review-loop.** The "Источник" (Source) column is last; `/fix` reads it only to tag the logged outcome.
- **No `файл:строка` or no failure scenario → not a finding.** Dropped before the table, counted under it. Severity scale and the `[both]/[claude]/[codex]` logic are unchanged.
- **Sort before matching.** On a tree behind main, ahead of it, or dirty outside the change, 5.0 checks both sources against main by `/codereview` Step 0; phantoms are dropped and counted, `OLD-` rows stay out of the verdict, `/fix` and the loops.
- **Fallback to single-review when Codex is unavailable.** Don't crash — degrade with a clear message.
- **Don't write a direct git commit/push** — that's `/sup-push`.
