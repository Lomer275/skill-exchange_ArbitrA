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

If nothing is passed and there is no 🟡 in HANDOFF — ask the user.

---

## Algorithm

### Step 0 — Routing checks (kill-switch + availability)

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

If `available=false` — graceful fallback to single-review (see Step 5 fallback).

---

### Step 1 — Gather context

1. Find the task file: glob `docs/3. SUP-tasks/T<NN>_*.md` (or from HANDOFF).
2. Read the task file: acceptance criteria, description, affected files.
3. Determine the specification path (from the `**Спецификация:**` line).
4. Read the changed code files (if listed or provided).

If the code is not provided and not specified in the task — ask the user to attach it.

---

### Step 2 — Parallel start of the Codex reviewer

In a single message (without delays):

```
Skill(skill="codex-worker", args="role=reviewer task_file=docs/3. SUP-tasks/T<NN>_<name>.md spec_file=docs/2. SUP-specifications/S<NN>_<name>.md scope=read-only lens=correctness,edge-cases,risks timeout_min=5 task_id=T<NN>")
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
- **Phase B — adversarial:** "How will this code break?" Correctness, security, contract, performance, dead code.
- **Phase C — user walkthrough:** 3-5 scenarios (happy/empty/error/edge/concurrent).
- **Phase D — architectural fit:** conformance to project patterns.

Build your own findings table with columns: `ID, Severity, Фаза, Файл:строка, Категория, Описание, Рекомендация`.

**Categories** (for matching): `acceptance-criteria`, `correctness`, `security`, `performance`, `style`, `dead-code`, `architecture`, `edge-case`.

---

### Step 4 — Collect Codex output (poll)

After finishing your own phases — `Read(output_file)` from codex-worker.

- File exists and is non-empty → parse the Codex table.
- File is empty → poll every 2-3 sec until it becomes non-empty, limit — `timeout_min` (5 min).
- Codex crashed / `status: timeout|error` → fallback (Step 5).

**Parsing the Codex table:** expect a markdown table with the same columns. If the format is different — naive line-by-line parsing, or fallback.

---

### Step 5 — Merge findings (or fallback)

#### 5a — Full merge (Codex returned a result)

**Matching algorithm (R11):**

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

If `availability_cache.available=false` or Codex returned `status: timeout|error`:

To chat:
```
⚠️ Codex unavailable (<reason>). Doing a single-review (Claude only).
```

Use only your own findings, with a marker in the table header `[fallback: claude-only, Codex unavailable: <reason>]`.

---

### Step 6 — Write to the task file

In the task file (`docs/3. SUP-tasks/T<NN>_*.md`) add/update the section:

```markdown
## Code Review (dual)

**Дата:** YYYY-MM-DD
**Ревьюеры:** Claude (фазы A/B/C/D), Codex (correctness/edge-cases/risks)
**Найдено:** N CRITICAL, M HIGH, K MEDIUM, L LOW
**Расхождения:** X [severity-disputed]

| ID | Severity | Фаза | Файл:строка | Описание | Рекомендация | Источник |
|----|----------|------|-------------|----------|--------------|----------|
| R1 | CRITICAL | B | ... | ... | ... | [both] |
| R2 | HIGH | A | ... | ... | ... | [claude] |
| R3 | HIGH | B | ... | ... | ... | [codex] |
| R4 | MEDIUM | C | ... | ... | ... | [both, severity=max(claude=LOW, codex=MEDIUM)→MEDIUM] |
```

If the section already existed — add a new one (don't overwrite old reviews), marking it with a date.

---

### Step 7 — Final report to chat

```markdown
## /codereview-dual — Done

**Task:** T<NN> — <name>
**Found:** N CRITICAL, M HIGH, K MEDIUM, L LOW
**Sources:** [both]: <count> | [claude]: <count> | [codex]: <count>
**Severity disagreements:** <count> [severity-disputed]

**Task file updated:** docs/3. SUP-tasks/T<NN>_*.md (section `## Code Review (dual)`)

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
- **Output is compatible with /fix and /review-loop.** The "Источник" (Source) column is last; downstream skills ignore it.
- **Fallback to single-review when Codex is unavailable.** Don't crash — degrade with a clear message.
- **Don't write a direct git commit/push** — that's `/sup-push`.
