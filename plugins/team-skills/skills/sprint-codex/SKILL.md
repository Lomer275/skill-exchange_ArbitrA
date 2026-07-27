---
name: sprint-codex
description: >
  Parallel sprint via Codex workers in a git worktree. Reads the spec, builds
  waves by dependencies, classifies the wave (shared directory vs worktree-per-task
  if tasks touch shared/ or common risk points), and launches N Codex implementers
  in parallel. After merging the whole wave, it delegates review to /review-loop (does NOT call
  /codereview-dual directly — otherwise a double review). Use when the user
  says "/sprint-codex", "/sprint-codex S05", "параллельный спринт", "спринт через
  кодекс", or when routing decides on sprint-codex (Codex available and wave ≥2 tasks).
  Part of spec S11, Phase 4.
---

# /sprint-codex — Parallel sprint via Codex workers

Drop-in replacement for `/sprint` for waves of ≥2 tasks. Codex implementers work in parallel in worktrees; Claude orchestrates merge → review-loop → accept → push.

---

## Input

- `/sprint-codex S05` — the specification number is required.
- `/sprint-codex S05 --dry-run` — show the wave plan without executing.

If the number is not provided, ask the user for it.

---

## Algorithm

### Step 0 — Routing checks

Same as in `/codereview-dual`:

1. **Kill-switch** (`.claude/codex.json:enabled` + env `SUP_CODEX_ENABLED` with a precedence matrix). When disabled — refuse to start with a hint to enable it via `/codex-toggle on`, or offer to run classic `/sprint`.
2. **Availability cache.** Fresh check if the cache is stale.
3. **Min CLI version + pre-warm (auth-race safety).** Verify `codex --version` ≥ **0.143.0** — older CLIs race the OAuth refresh under parallel workers and fail intermittently with `refresh_token_reused (401)` ([openai/codex#10332](https://github.com/openai/codex/issues/10332)); if lower, tell the user to upgrade (`npm i -g @openai/codex@latest`) before running a parallel sprint. Then **pre-warm once, before any fan-out:** `timeout 20 codex exec --skip-git-repo-check "ok"`. This starts the shared app-server daemon and refreshes the token serially, so the N parallel workers in Step 3.3 attach to a **warm** daemon and none triggers a cold-start refresh race. All workers keep the **shared** `CODEX_HOME` — never isolate it per worktree (see codex-worker Rules; worktree isolation is for files/`--cwd` only).

If `available=false` — STOP with a suggestion to use `/sprint` (classic).

---

### Step 1 — Parsing the spec

1. Read `docs/2. SUP-specifications/S<NN>_*.md`.
2. Extract the task table: `ID`, `Зависит от`, `Фаза`, `Статус`.
3. For each draft task, read the file (`docs/3. SUP-tasks/T<NN>_*.md`):
   - Acceptance criteria.
   - Affected files (from the text or an explicit section).

---

### Step 2 — Building waves (topological sort)

```python
def build_waves(tasks):
    waves = []
    completed = set(t.id for t in tasks if t.status == '✅')
    pending = [t for t in tasks if t.status != '✅']
    while pending:
        wave = [t for t in pending if all(d in completed for d in t.deps)]
        if not wave:
            raise CycleError("circular dependency or non-completed deps")
        waves.append(wave)
        for t in wave:
            completed.add(t.id)
        pending = [t for t in pending if t not in wave]
    return waves
```

To chat: show the wave plan.

```markdown
## /sprint-codex S<NN> — Plan

**Waves:** N
**Total tasks:** M

### Wave 1: <task-ids> (parallel)
### Wave 2: ...
```

On `--dry-run` — STOP here.

---

### Step 3 — Loop over waves

For each wave:

#### 3.1 — Classification (shared directory vs worktree)

Gather the set of files for each task (from acceptance criteria + current code via `git grep`/`find`).

**Rules:**
- If the sets **do not overlap** AND no task touches common risk points — shared directory.
- Otherwise — worktree per task.

**Common risk points:**
- `shared/` (any file).
- `tg_bot/texts.py`.
- `tg_bot/keyboards.py`.
- `Handler/models.py`.

To chat: "Wave N: <shared directory|worktree-per-task>, reason: <...>".

#### 3.2 — Preparing the worktree (if needed)

For each task in the wave:

```bash
WT_PATH="/tmp/sup-codex-wt/T${NN}-${SLUG}"
BRANCH="codex/T${NN}-${SLUG}"

# Collision check (R6)
if [ -e "$WT_PATH" ]; then
  TS=$(date +%s)
  mv "$WT_PATH" "${WT_PATH}.failed-${TS}"
  echo "⚠️ Existing worktree saved: ${WT_PATH}.failed-${TS}"
  # rename the branch if it exists
  if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
    git branch -m "$BRANCH" "${BRANCH}-failed-${TS}"
  fi
fi

# Create fresh worktree
git worktree add "$WT_PATH" -b "$BRANCH"

# venv passthrough (R3): symlink if venv is in the repo
if [ -d "$(git rev-parse --show-toplevel)/.venv" ] && [ ! -e "$WT_PATH/.venv" ]; then
  ln -s "$(git rev-parse --show-toplevel)/.venv" "$WT_PATH/.venv"
fi
```

To chat, for each task: "Created worktree T<NN>: $WT_PATH".

#### 3.3 — Launching Codex workers in parallel

In **a single message** (for true parallelism), make N calls:

```
Skill(skill="codex-worker", args="role=implementer task_file=docs/3. SUP-tasks/T<NN>_<name>.md spec_file=docs/2. SUP-specifications/S<NN>_<name>.md worktree=<WT_PATH-or-current> scope=edit:<paths> timeout_min=10 task_id=T<NN>")
```

Save all task_id and output_file values for each worker.

To chat:
```
🚀 Wave N: launched <K> Codex workers in parallel.
```

#### 3.4 — Collecting results

Wait for all workers to finish. In parallel, `Read(output_file)` for each. On completion (or timeout) — assemble the reports:

```markdown
**Wave N — Results:**
- T<NN1>: ✅ ok (<duration>s) — <brief summary from output>
- T<NN2>: ⚠️ timeout — debug in /tmp/sup-codex-wt/T<NN2>-...failed-<ts>
- T<NN3>: ✅ ok (<duration>s) — ...
```

#### 3.5 — Merging branches

Only for **successful** workers. Sequentially:

```bash
cd <repo-root>
git merge "codex/T<NN>-<slug>"
```

On a conflict:
- Show `git status` to the user.
- Ask: "Resolve manually or roll back this task?"
- Act according to the answer.

On a successful merge:
```bash
git worktree remove "/tmp/sup-codex-wt/T<NN>-<slug>"
git branch -d "codex/T<NN>-<slug>"
```

Failed worktrees (with `.failed-<ts>`) are **not removed** — they remain for debugging.

---

### Step 4 — After all waves: review + accept + push

**IMPORTANT (R5):** do not call `/codereview-dual` directly. `/review-loop` will decide dual or single itself via routing.

```
1. /review-loop  — for all changes as a batch
   └─ internally it calls /codereview (via routing → /codereview-dual)
   └─ and /fix until clean of CRITICAL/HIGH

2. For each task in the waves: /accept T<NN>

3. /sup-push  — one commit for the whole batch (or one per task,
                ask the user at the start of the sprint)
```

---

### Step 5 — Cleanup

```bash
# Files older than 7 days in /tmp/sup-codex/
find /tmp/sup-codex -type f -mtime +7 -delete 2>/dev/null

# keep last-run.log for debugging
```

---

### Step 6 — Final report

```markdown
## /sprint-codex — Done

**Spec:** S<NN>
**Waves processed:** N
**Tasks completed:** ✅ K | ⚠️ failed: M

### Per-task:
| ID | Status | Duration | Worktree |
|----|--------|----------|----------|
| T77 | ✅ merged | 5m | (shared directory) |
| T78 | ✅ merged | 8m | T78-<slug> (cleaned) |
| T79 | ⚠️ timeout | 10m | T79-<slug>.failed-<ts> (debug) |

### Review-loop: <clean | N iterations, MEDIUM/LOW remaining>
### Accept: ✅ K tasks
### Push: ✅ <commit hash> (or: commit awaiting an explicit /sup-push)

**Failed tasks:** require manual triage. Debug snapshots in /tmp/sup-codex-wt/*.failed-*
```

---

## Rules

- **Routing is the first step.** Do not start without the kill-switch + availability checks.
- **Parallelism via `Bash(run_in_background=true)`** — N calls to `Skill("codex-worker", ...)` in a single message (not sequentially).
- **Worktree creation is sequential** (to avoid races), but the workers inside them run in parallel.
- **Collision check (R6) before each `git worktree add`** — rename an occupied path to `.failed-<ts>`.
- **venv passthrough (R3)** — symlink `.venv` into the worktree + env variables via `codex-worker`.
- **After merge — only `/review-loop`** (R5), without a direct `/codereview-dual`.
- **Do not remove failed worktrees automatically** — keep them under `.failed-<ts>` for debugging.
- **Merge conflicts — interactive with the user**, not automatic resolution.
- **Cleanup `/tmp/sup-codex/` older than 7 days** (R16) — at the start of each sprint.
- On a circular dependency in the waves — STOP with a clear error.
