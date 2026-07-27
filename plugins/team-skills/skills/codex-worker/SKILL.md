---
name: codex-worker
description: "Internal helper for launching a Codex worker. NOT invoked by the user directly — called from /impl, /fix, /codereview-dual and /sprint-codex via the Skill tool. Accepts either a TNN task file (spec-driven path) or an ad-hoc brief_file (the /impl path). Builds a prompt file and runs Codex through the codex@openai-codex plugin engine (app-server, no bubblewrap); fallback — legacy codex exec. Checks the kill-switch (.claude/codex.json + SUP_CODEX_ENABLED), watchdog via TaskStop. Returns {status, output_file, task_id, duration_s}. Part of spec S11, Phase 2."
---

# codex-worker — Internal helper for launching a Codex worker

**This is an internal helper.** Do not run in response to a user message. The only trigger is a call via `Skill(skill="codex-worker", args="...")` from another skill.

As of 2026-06-11 the worker launches Codex **through the `codex@openai-codex` plugin engine** (`codex-companion.mjs task`, app-server protocol). This removes the dependency on the bubblewrap sandbox and the entire inline fallback. If the engine is not found — graceful fallback to legacy `codex exec` (see Appendix A).

---

## Call contract

**Args** (passed as the string `key1=value1 key2=value2 ...`):

| Parameter | Required | Default | Description |
|----------|-----------|---------|----------|
| `role` | yes | — | `reviewer` or `implementer` |
| `task_file` | one of | — | path to the task file (TNN_*.md) — the spec-driven path (`/sprint-codex`, `/codereview-dual`) |
| `brief_file` | one of | — | path to an ad-hoc brief (`/tmp/sup-codex/impl-*-brief.md`) — the `/impl` path, no TNN file involved |
| `spec_file` | no | — | path to the specification (SNN_*.md) |
| `worktree` | no | `current` | abs path to the worktree or `current` |
| `scope` | yes | — | `read-only` for reviewer, `edit:<paths>` for implementer |
| `lens` | for reviewer | `correctness` | review lens: `correctness,edge-cases,risks,security,style,...` |
| `timeout_min` | no | `10` | watchdog timeout in minutes |
| `task_id` | no | file name | prefix for prompt/output files (e.g. `T17`) |
| `model` | no | — | Codex model override (`spark` → `gpt-5.3-codex-spark`); empty = default |
| `effort` | no | — | reasoning effort: `none\|minimal\|low\|medium\|high\|xhigh`; empty = default |
| `inline` | no | `auto` | **legacy mode only** (Appendix A). Ignored in companion mode |
| `inline_files` | no | — | **legacy mode only**. Ignored in companion mode |

**Return** (as structured text — the contract is unchanged):

```
status: ok | timeout | disabled | error
output_file: <path>
task_id: <claude-code-bash-task-id>
duration_s: <число>
notes: <если есть проблемы>
```

`output_file` always contains **Codex's final message** (in companion mode — the `rawOutput` field extracted from `--json`). The calling skill reads exactly this file.

---

## Algorithm

### Step 1 — Parsing args

Extract the variables from args. Validation:
- `role` ∈ {reviewer, implementer}
- **exactly one** of `task_file` / `brief_file` is given, and it exists (`Read` to check). Both given → prefer `task_file`, note it. Neither → `status: error`.
- `scope` is non-empty
- `timeout_min` > 0

> `brief_file` is the ad-hoc path introduced for `/impl`: the source of truth for the worker is a brief written by Claude, not a TNN task file. Everything downstream (engine, watchdog, return contract) is identical — only the prompt's source document differs.

If invalid — return `status: error, notes: <reason>`.

---

### Step 2 — Kill-switch check

Read `.claude/codex.json` and apply the precedence matrix (env > file):

```bash
ENV_VAL="${SUP_CODEX_ENABLED:-}"
case "$ENV_VAL" in
  true|1|yes)   FINAL=true ;;
  false|0|no)   FINAL=false ;;
  "")           FINAL=$(jq -r '.enabled' .claude/codex.json) ;;
  *)            FINAL=$(jq -r '.enabled' .claude/codex.json)
                # warning: невалидный env, использовать файл
                ;;
esac
```

If `FINAL=false` — return `status: disabled, notes: kill-switch active`.

---

### Step 3 — Engine resolution (companion vs legacy)

```bash
COMPANION=$(ls -d "$HOME"/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | sort -V | tail -1)
```

- `COMPANION` is non-empty and the file exists → **companion mode** (Steps 4–7 below).
- Otherwise → **legacy mode** (Appendix A). Log `notes: companion not found, legacy codex exec`.

> Companion is the `codex@openai-codex` plugin engine. It is maintained by OpenAI and uses the app-server protocol rather than `codex exec` + bubblewrap. The path is resolved by glob (the version in the path is not hardcoded — it survives plugin updates).

---

### Step 4 — Building the prompt file

```bash
mkdir -p /tmp/sup-codex
PROMPT_FILE="/tmp/sup-codex/${TASK_ID}-${ROLE}-prompt.txt"
OUTPUT_FILE="/tmp/sup-codex/${TASK_ID}-${ROLE}.txt"
RAW_JSON="/tmp/sup-codex/${TASK_ID}-${ROLE}.json"

# Коллизия имён — uuid-суффикс (R15/R18)
if [ -e "$OUTPUT_FILE" ]; then
  UUID=$(uuidgen | head -c 8)
  PROMPT_FILE="/tmp/sup-codex/${TASK_ID}-${ROLE}-${UUID}-prompt.txt"
  OUTPUT_FILE="/tmp/sup-codex/${TASK_ID}-${ROLE}-${UUID}.txt"
  RAW_JSON="/tmp/sup-codex/${TASK_ID}-${ROLE}-${UUID}.json"
fi
```

**Prompt file content** (adapt to the role). In companion mode Codex reads files through its shell tools as usual — **inline embedding is not needed**:

```text
CONTEXT: WORKER
ROLE: <role>
ORCHESTRATOR: Claude Code в проекте Arbitra_support (SUP).

TASK_FILE: <task_file>            # либо
BRIEF_FILE: <brief_file>          # одно из двух — что передано
SPEC_FILE: <spec_file (или "не указан")>
WORKTREE: <worktree>
SCOPE: <scope>
LENS (для reviewer): <lens>

DO:
- Прочитай TASK_FILE (или BRIEF_FILE), SPEC_FILE и AGENTS.md в корне.
- Выполни задачу строго в SCOPE.
- BRIEF_FILE — это готовый бриф от оркестратора: подход уже выбран, твоя работа —
  реализовать его, а не проектировать заново. Расходишься с брифом — так и напиши
  в финальном сообщении, но сначала сделай как написано.
<если role=implementer>:
- Малые точечные правки, без рефакторинга вне задачи.
- Используй `python` из $VIRTUAL_ENV/bin/python для всех запусков (если работаешь в worktree).
<если role=reviewer>:
- Top findings с severity, evidence (файл:строка), recommended fixes.
- Линзы: <lens>.

OUTPUT (финальное сообщение):
- Что сделано / найдено.
- Изменённые файлы (для имплементера).
- Риски и follow-ups (кратко).

DO NOT:
- Спавнить других воркеров.
- Расширять scope.
- Делать git commit/push.
- Трогать .env*, CHANGELOG.md, HANDOFF.md.
```

Write it via `Write` to `$PROMPT_FILE`.

---

### Step 5 — Building the companion command

```bash
# worktree → --cwd; current → текущий каталог
WT_FLAG="--cwd ${WORKTREE:-$PWD}"
[ "$WORKTREE" = "current" ] && WT_FLAG="--cwd $PWD"

# role → sandbox: implementer пишет (--write), reviewer read-only
WRITE_FLAG=""
[ "$ROLE" = "implementer" ] && WRITE_FLAG="--write"

# model/effort: явный arg > ~/.codex/config.toml > пусто (app-server default).
# ВАЖНО: companion (app-server) НЕ наследует config.toml автоматически — без этого
# воркер ревьюит на лёгком дефолте, а legacy `codex exec` — на gpt-5.5/high. Пробрасываем для паритета.
CFG="$HOME/.codex/config.toml"
if [ -z "$MODEL" ]  && [ -f "$CFG" ]; then
  MODEL=$(grep -E '^[[:space:]]*model[[:space:]]*=' "$CFG" | head -1 | sed -E 's/.*=[[:space:]]*"?([^"#]+)"?.*/\1/' | xargs)
fi
if [ -z "$EFFORT" ] && [ -f "$CFG" ]; then
  EFFORT=$(grep -E '^[[:space:]]*model_reasoning_effort[[:space:]]*=' "$CFG" | head -1 | sed -E 's/.*=[[:space:]]*"?([^"#]+)"?.*/\1/' | xargs)
fi
# effort должен быть из {none,minimal,low,medium,high,xhigh}; иначе companion упадёт — отбрасываем невалидное
case "$EFFORT" in none|minimal|low|medium|high|xhigh) ;; *) EFFORT="" ;; esac
MODEL_FLAG="";  [ -n "$MODEL" ]  && MODEL_FLAG="--model $MODEL"
EFFORT_FLAG=""; [ -n "$EFFORT" ] && EFFORT_FLAG="--effort $EFFORT"

ERR_FILE="/tmp/sup-codex/${TASK_ID}-${ROLE}.err"
```

**Env passthrough (venv in worktree, R3) — via the real `env` command, NOT a prefix variable.**
In bash, `$PRE cmd` from a variable expansion does **not** recognize `VAR=val` as an assignment (verified empirically) — so we build the arguments for `env` and invoke the command directly (without a `CMD` string with fake quotes):

```bash
ENV_ARGS=""
[ -n "$VIRTUAL_ENV" ]            && ENV_ARGS="$ENV_ARGS PATH=$VIRTUAL_ENV/bin:$PATH VIRTUAL_ENV=$VIRTUAL_ENV"
[ -n "$PYTHONPATH" ]             && ENV_ARGS="$ENV_ARGS PYTHONPATH=$PYTHONPATH"
[ -n "$DJANGO_SETTINGS_MODULE" ] && ENV_ARGS="$ENV_ARGS DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE"
```

---

### Step 6 — Background launch + watchdog

Launch via `Bash(run_in_background=true)`, redirecting stdout to `$RAW_JSON` and stderr to `$ERR_FILE`:

```bash
env $ENV_ARGS node "$COMPANION" task --json $WT_FLAG $WRITE_FLAG $MODEL_FLAG $EFFORT_FLAG \
  --prompt-file "$PROMPT_FILE" > "$RAW_JSON" 2> "$ERR_FILE"
```

Get the `task_id` (claude-code bash task id). Record the start time. Then the watchdog poll loop:

```python
# псевдокод алгоритма Claude:
deadline = now() + timeout_min*60
while now() < deadline:
    if exists(RAW_JSON) and size(RAW_JSON) > 0:
        # companion завершился — распарсить JSON
        try:
            data = json.load(RAW_JSON)
            write(OUTPUT_FILE, data.get("rawOutput", ""))
            status = "ok" if data.get("status") == 0 else "error"
            notes  = "" if status == "ok" else f"companion status={data.get('status')}; see .err"
            return {status, output_file: OUTPUT_FILE, task_id, duration_s, notes}
        except JSONError:
            # частичный/битый stdout — подождать ещё цикл, при повторе → error
            ...
    # H1: ранний выход — процесс завершился, но RAW_JSON пуст → companion упал (auth/модель/краш).
    # НЕ ждать весь timeout: вернуть error с причиной из ERR_FILE сразу.
    if task_finished(task_id) and (not exists(RAW_JSON) or size(RAW_JSON) == 0):
        err = read(ERR_FILE)[:500]
        return {status:"error", output_file:OUTPUT_FILE, task_id, duration_s, notes:f"companion exited without output: {err}"}
    sleep(2-3s)

# таймаут
TaskStop(task_id=task_id)
return {status:"timeout", output_file:OUTPUT_FILE, task_id, duration_s:timeout_min*60, notes:"watchdog killed"}
```

In Claude Code: `Bash(run_in_background=true)` to start, then periodically `Read(RAW_JSON)` (check existence + non-emptiness + JSON validity) **and** `BashOutput(task_id)` to detect early process termination, while watching the time in parallel. At the deadline — `TaskStop(task_id)`. If it finished on its own with an empty `RAW_JSON` → `status:error` (see H1), not `timeout`.

> **Why `rawOutput` → `OUTPUT_FILE`:** calling skills read `output_file` as Codex's final message. Companion returns it in the `rawOutput` JSON field; we extract it and put it into the file, preserving the contract.
> **`touchedFiles`** from companion is unreliable (may be empty even on a real write) — `sprint-codex` determines the changed files via `git`, do not trust this field.

---

### Step 7 — Final log + Return

```bash
echo "$(date -Iseconds) ${ROLE} ${TASK_ID} engine=companion status=${STATUS} duration=${DURATION}s output=${OUTPUT_FILE}" >> /tmp/sup-codex/last-run.log
```

Return the structured result (the contract from the "Call contract" section). The calling skill reads the result and decides what to do next (process the output, fallback, retry).

---

## Rules

- **Do NOT run directly in response to a user message.** Only via the Skill tool from other skills.
- **Do NOT spawn other workers.** A worker is terminal.
- **One call = one Codex worker.** Parallelism is achieved by calling N times from the parent skill.
- **Concurrency & shared `CODEX_HOME` (auth-race safety).** All parallel workers MUST share **one** `CODEX_HOME` (default `~/.codex`). Do **NOT** set a per-worker or per-worktree `CODEX_HOME`: each home spins up its own app-server daemon with a separate `auth.json` copy that still holds the **same single-use** refresh_token — concurrent workers then race the OAuth refresh and fail intermittently with `refresh_token_reused (401)` ([openai/codex#10332](https://github.com/openai/codex/issues/10332)). A shared home serializes refresh via the daemon + `refresh.lock`. **Requires Codex CLI ≥ 0.143.0** (the release that added the cross-process refresh lock). On older CLIs parallel waves are unstable — upgrade per user: `npm i -g @openai/codex@latest`. File isolation for worktrees is fine (that's `--cwd`); it must never extend to `CODEX_HOME`.
- **Naming convention:** `<task_id>-<role>[-<uuid8>]-prompt.txt`, `.txt` (output), `.json` (raw). UUID suffix on collision (R15, R18).
- **On a launch error** (no companion AND no codex binary, auth fail) — return `status: error, notes: <reason>` with a clear message.
- **Logs** in `/tmp/sup-codex/last-run.log` and `<task_id>-<role>.err` for debugging.
- **Companion mode is primary**, legacy is the fallback when the plugin is absent. Do not call the plugin's `/codex:*` commands directly — only `codex-companion.mjs task` as a subprocess.

---

## Appendix A — Legacy mode (`codex exec`, fallback)

Used **only** when the plugin engine is not found (Step 3). Kept for environments without `codex@openai-codex` installed.

Differences from companion mode:
1. **Sandbox capability detection (T82/T83).** The Codex CLI requires `bubblewrap` for shell tools; it is not present on dev. Probe `codex exec --skip-git-repo-check "pwd"`, a three-state result (`true/false/unknown`), TTL cache of 1h in `.claude/codex.json:availability_cache.sandbox_works`. On `false`/`unknown` → inline mode.
2. **Inline prompt assembly.** When `INLINE_MODE=true`, the content of `inline_files` (or TASK_FILE+SPEC_FILE) is embedded at the end of the prompt (limit ~100KB, priority TASK > SPEC > ARTEFACTS), with a "DO NOT use shell tools" note. The `inline`/`inline_files` parameters from the contract apply only here.
3. **Launch:** `cli_flags` from codex.json (`output_last_message`, `skip_git_repo_check`):
   ```bash
   cd <worktree-or-cwd>
   $ENV_PREFIX codex exec $SKIP_GIT_FLAG $OUTPUT_FLAG "$OUTPUT_FILE" "$(cat $PROMPT_FILE)"
   ```
   Here Codex itself writes the final message to `$OUTPUT_FILE` via `--output-last-message` (no JSON parsing needed).
4. **Watchdog** — the same: `Bash(run_in_background)` → poll `OUTPUT_FILE` for non-emptiness → `TaskStop` at the deadline.

The return contract is identical. In `notes` specify `engine=legacy`.
