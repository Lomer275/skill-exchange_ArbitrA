---
name: sprint-codex
description: >
  Parallel sprint via Codex workers in a git worktree. Reads the spec, builds
  waves by dependencies, classifies the wave (shared directory vs worktree-per-task
  if tasks touch profile shared_paths), and launches N Codex implementers
  in parallel. After merging the whole wave, it delegates review to /review-loop (does NOT call
  /codereview-dual directly — otherwise a double review). Use when the user
  says "/sprint-codex", "/sprint-codex S05", "параллельный спринт", "спринт через
  кодекс", or when routing decides on sprint-codex (Codex available and wave ≥2 tasks).
  Part of spec S11, Phase 4.
  If the project or the user has its own `sprint-codex` skill, that one takes precedence — use this one only when the user typed `/team-skills:sprint-codex` or no such skill exists.
---

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:sprint-codex` and a skill named `sprint-codex` exists in the project (`.claude/skills/sprint-codex/SKILL.md`) or in the user's skills (`~/.claude/skills/sprint-codex/SKILL.md`), stop: tell the user that their own `/sprint-codex` takes precedence, and do nothing else.

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

Before routing or launching anything, require `.claude/team-skills.json` version 1 and keys `docs.specifications`, `docs.tasks`, `shared_paths`.
Missing file, invalid version or missing key → stop, name the missing item and point to `/team-skills:init_dev` and `docs/team-skills-profile.md` in the catalog. No guessed prefix or fallback paths.
All document paths are repository-relative. Resolve TASKS_DIR from `docs.tasks` and SPECS_DIR from `docs.specifications`.

Resolve the push skill from `commands.push` in `.claude/team-skills.json`; if the file/key is absent use `/team-skills:safe-push` (the only command default). References to `<push-command>` below mean this resolved command.

# /sprint-codex — Parallel sprint via Codex workers

Drop-in replacement for `/sprint` for waves of ≥2 tasks. Codex implementers work in parallel in worktrees; Claude orchestrates authorized merge → review-loop, then offers accept and push to the human.

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
3. **Min CLI version + pre-warm (auth-race safety).** Verify `codex --version` ≥ **0.143.0** — older CLIs race the OAuth refresh under parallel workers and fail intermittently with `refresh_token_reused (401)` ([openai/codex#10332](https://github.com/openai/codex/issues/10332)); if lower, tell the user to upgrade (`npm i -g @openai/codex@latest`) before running a parallel sprint. Then **pre-warm once, before any fan-out:** `timeout 20 codex exec -m "$MODEL" -c model_reasoning_effort=low --skip-git-repo-check "ok" < /dev/null`. This starts the shared app-server daemon and refreshes the token serially, so the N parallel workers in Step 3.3 attach to a **warm** daemon and none triggers a cold-start refresh race. All workers keep the **shared** `CODEX_HOME` — never isolate it per worktree (see codex-worker Rules; worktree isolation is for files/`--cwd` only).

If `available=false` — STOP with a suggestion to use `/sprint` (classic).

---

### Step 1 — Parsing the spec

1. Read `${SPECS_DIR}/S<NN>_*.md`.
2. Extract the task table: `ID`, `Зависит от`, `Фаза`, `Статус`.
3. For each draft task, read the file (`${TASKS_DIR}/T<NN>_*.md`):
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

**Common risk points:** use only the profile `shared_paths` array. If multiple tasks in a wave touch a listed path, use worktree-per-task; an empty array defines no additional risk paths.

To chat: "Wave N: <shared directory|worktree-per-task>, reason: <...>".

#### 3.2 — Preparing the worktree (if needed)

**Never under `/tmp`, never from the current HEAD, never merging into the main checkout.**
Some hosts wipe `/tmp` nightly (worktrees and their branches' work vanish), and a shared main
checkout may be a mix of branches — building on it drags foreign
changes into the sprint. Worktrees live in `$WT_ROOT` — `<repo>-wt/`, next to the main checkout.
Shell state does not carry over between calls, so every command below that names `$WT_ROOT` starts with:

```bash
WT_ROOT="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")-wt"
```

Layout:

- **Sprint branch** `feat/<spec>-sprint<N>` from `origin/main`, in its own worktree
  `$WT_ROOT/<spec>-sprint<N>` — created once, before wave 1:
  ```bash
  git fetch -q origin main
  git worktree add -b "feat/${SPEC}-sprint${N}" "$WT_ROOT/${SPEC}-sprint${N}" origin/main
  ```
- **Task branches** from the sprint branch (so wave 2 sees wave 1), one worktree per task.
- If the task files are not on `origin/main` yet (spec PR still open), pass them to the worker
  by absolute path from the worktree where they live.

For each task in the wave:

```bash
WT_PATH="$WT_ROOT/${SPEC}-T${NN}"
BRANCH="codex/T${NN}-${SLUG}"
SPRINT_BRANCH="feat/${SPEC}-sprint${N}"

# Collision check (R6)
if [ -e "$WT_PATH" ]; then
  TS=$(date +%s)
  # git worktree move, not mv: a plain mv leaves a stale registration and the next add fails
  git worktree move "$WT_PATH" "${WT_PATH}.failed-${TS}" 2>/dev/null || mv "$WT_PATH" "${WT_PATH}.failed-${TS}"
  echo "⚠️ Existing worktree saved: ${WT_PATH}.failed-${TS}"
  # rename the branch if it exists
  if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
    git branch -m "$BRANCH" "${BRANCH}-failed-${TS}"
  fi
fi

# Create fresh worktree from the sprint branch (not from the current HEAD)
git worktree add "$WT_PATH" -b "$BRANCH" "$SPRINT_BRANCH"

# venv passthrough (R3): symlink if venv is in the repo
if [ -d "$(git rev-parse --show-toplevel)/.venv" ] && [ ! -e "$WT_PATH/.venv" ]; then
  ln -s "$(git rev-parse --show-toplevel)/.venv" "$WT_PATH/.venv"
fi
```

To chat, for each task: "Created worktree T<NN>: $WT_PATH".

#### 3.3 — Launching Codex workers in parallel

In **a single message** (for true parallelism), make N calls:

```
Skill(skill="codex-worker", args="role=implementer model=<resolved-model> effort=<resolved-effort> task_file=${TASKS_DIR}/T<NN>_<name>.md spec_file=${SPECS_DIR}/S<NN>_<name>.md worktree=<WT_PATH-or-current> scope=edit:<paths> timeout_min=10 task_id=T<NN>")
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
- T<NN2>: ⚠️ timeout — debug in <repo>-wt/<spec>-T<NN2>.failed-<ts>
- T<NN3>: ✅ ok (<duration>s) — ...
```

**Scope gate per worker — before reading its diff.** If `scripts/staff/scope_check.py` exists, run it; otherwise compare the union of `git diff --name-only` and `git ls-files --others --exclude-standard` in that worker tree against the task allowed paths. Any extra file → STOP and show it. Manually read the diff and verify task DoD before marking the fallback gate green. The task file is the brief: its `## ФАЙЛЫ` section is the allowed list.

```bash
python3 scripts/staff/scope_check.py --brief "<abs path to T<NN>_*.md>" --repo "$WT_PATH" \
  --base "$SPRINT_BRANCH" --format text --task T<NN> > ~/sup-codex/T<NN>-scope.txt; echo "exit=$?"
```

- `--base` is the **sprint branch**, not `origin/main`: after wave 1 is merged, `origin/main` as base would charge earlier tasks' files to this one.
- Exit `0` → read the diff against the task, queue it for the wave approval below (do not commit yet; Codex does not commit). `owner_review:` paths are listed in the final report.
- Exit `1` → **one** corrective run of the same worker: the prompt gets a `# ПРАВКИ ПО РЕВЬЮ` section with the gate output. Second RED → the task is ⚠️, its branch is **not merged**, the rest of the wave goes on.
- Exit `2` → the task file has no usable `ФАЙЛЫ` or the base is wrong — fix the task file / command, not the worker.
- `lint_unavailable` → install ruff (`/usr/bin/python3 -m pip install --user ruff`) and re-run; not a worker miss.
- A task that edits only `.claude/` (not in git) → the gate does not apply; Claude does it directly anyway.

#### 3.4b — One explicit human approval per wave (mandatory)

After collecting and reviewing every eligible task, show ONE concrete wave plan:
task IDs, exact changed file lists per task, proposed commit messages, target sprint
branch and merge actions, and exact task worktree/branch names proposed for deletion.
Ask for an explicit «да» in this dialog to that complete list. Before approval,
no task commit, merge, branch deletion or worktree removal is allowed.
If files, messages or actions change, present the revised list for approval.
After approval, commit only listed paths in each eligible task worktree, then
perform only the listed merges and cleanup in 3.5. In shared-directory mode,
the same gate covers its commits; never stage unrelated files.

`--yes`, cron, HANDOFF/config permissions and TG plan buttons do not authorize
these actions. In headless mode, STOP with status `ready to commit`, list files
and proposed messages, preserve all worktrees/branches, and notify through an
existing configured notification channel if available. No human → no commit or push.
Approval of a wave does not authorize push, PR creation/merge or later waves.

#### 3.5 — Merging branches

Only for workers with a **green gate** and a reviewed, committed diff. Sequentially, **into the sprint branch, in the sprint worktree** — never into the main checkout:

```bash
cd "$WT_ROOT/${SPEC}-sprint${N}"
git merge --no-ff --no-edit "codex/T<NN>-<slug>"
```

On a conflict:
- Show `git status` to the user.
- Ask: "Resolve manually or roll back this task?"
- Act according to the answer.

On a successful merge:
```bash
git worktree remove "$WT_ROOT/${SPEC}-T<NN>"
git branch -d "codex/T<NN>-<slug>"
```

Failed worktrees (with `.failed-<ts>`) are **not removed** — they remain for debugging.

---

### Step 4 — After all waves: review and offer next steps

Call only `/review-loop` for all changes as a batch; it owns review routing and fixes.
A limit, plateau or surviving blocker is not clean: report the blockers and stop.
Even when clean, do not automatically call accept or the resolved push command.
Offer `/team-skills:accept T<NN>` and `<push-command>` to the human and wait.
Show changed files and proposed action before asking. Commit permission does not
authorize push; PR creation/merge and branch/worktree deletion require explicit
approval for their concrete lists too. In headless mode report `ready to commit`
when uncommitted changes remain, or local commits awaiting human action otherwise,
and notify only if a channel is already configured. Never infer approval from
`/sprint --yes`, autopilot, config, HANDOFF or TG buttons.

---

### Step 5 — Cleanup

```bash
# Files older than 7 days in /tmp/sup-codex/ (prompts and raw worker output only;
# briefs and scope-gate output live in ~/sup-codex/ and are not swept here)
find /tmp/sup-codex -type f -mtime +7 -delete 2>/dev/null

# keep last-run.log for debugging
```

No worktrees under `/tmp` any more; task worktrees live in `<repo>-wt/` and are removed after their merge (3.5).

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

### Review-loop: <clean | N iterations, MEDIUM/LOW remaining | ⚠️ limit / plateau / survived two fix rounds — blockers remain>
### Accept: <offered; awaiting human decision | skipped — review-loop not clean>
### Push: <awaiting separate human approval | skipped — review-loop not clean> (or: ready to commit; awaiting human approval)

**Next** (only when review-loop is not clean or the push was refused): resolve the blockers by hand → `/review-loop` → `/accept` → `<push-command>`; a refused push → `<push-command>` by a human.

**Failed tasks:** require manual triage. Debug snapshots in <repo>-wt/*.failed-*
```

---

## Rules

- **After precedence and profile checks, run routing.** Do not start without the kill-switch + availability checks.
- **Parallelism via `Bash(run_in_background=true)`** — N calls to `Skill("codex-worker", ...)` in a single message (not sequentially).
- **Worktree creation is sequential** (to avoid races), but the workers inside them run in parallel.
- **Collision check (R6) before each `git worktree add`** — rename an occupied path to `.failed-<ts>`.
- **venv passthrough (R3)** — symlink `.venv` into the worktree + env variables via `codex-worker`.
- **Scope gate before every merge** — `--base` = sprint branch; two RED in a row → ⚠️, not merged.
- **Worktrees in `<repo>-wt/` next to the main checkout, merges into the sprint branch** — never `/tmp`, never the main checkout.
- **After merge — only `/review-loop`** (R5), without a direct `/codereview-dual`.
- **Do not remove failed worktrees automatically** — keep them under `.failed-<ts>` for debugging.
- **Merge conflicts — interactive with the user**, not automatic resolution.
- **Cleanup `/tmp/sup-codex/` older than 7 days** (R16) — at the start of each sprint.
- On a circular dependency in the waves — STOP with a clear error.
