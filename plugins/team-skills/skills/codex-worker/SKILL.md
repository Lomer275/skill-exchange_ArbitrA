---
name: codex-worker
description: "Internal helper для запуска Codex-воркера. НЕ зовётся пользователем напрямую — вызывается из /codereview-dual и /sprint-codex через Skill tool. Формирует prompt-файл и запускает Codex через движок плагина codex@openai-codex (app-server, без bubblewrap); fallback — legacy codex exec. Проверяет kill-switch (.claude/codex.json + SUP_CODEX_ENABLED), watchdog через TaskStop. Возвращает {status, output_file, task_id, duration_s}. Часть спеки S11, Phase 2."
---

# codex-worker — Internal helper для запуска Codex-воркера

**Это internal helper.** Не запускайся как ответ на сообщение пользователя. Триггер — только вызов через `Skill(skill="codex-worker", args="...")` из другого скилла.

С 2026-06-11 воркер запускает Codex **через движок плагина `codex@openai-codex`** (`codex-companion.mjs task`, app-server protocol). Это убирает зависимость от bubblewrap-песочницы и весь inline-fallback. Если движок не найден — graceful fallback на legacy `codex exec` (см. Приложение A).

---

## Контракт вызова

**Args** (передаются как строка `key1=value1 key2=value2 ...`):

| Параметр | Обязателен | Default | Описание |
|----------|-----------|---------|----------|
| `role` | да | — | `reviewer` или `implementer` |
| `task_file` | да | — | путь к файлу задачи (TNN_*.md) |
| `spec_file` | нет | — | путь к спецификации (SNN_*.md) |
| `worktree` | нет | `current` | abs путь worktree или `current` |
| `scope` | да | — | `read-only` для reviewer, `edit:<paths>` для implementer |
| `lens` | для reviewer | `correctness` | линза ревью: `correctness,edge-cases,risks,security,style,...` |
| `timeout_min` | нет | `10` | таймаут watchdog в минутах |
| `task_id` | нет | имя файла | префикс для prompt/output файлов (например `T17`) |
| `model` | нет | — | переопределение модели Codex (`spark` → `gpt-5.3-codex-spark`); пусто = дефолт |
| `effort` | нет | — | reasoning effort: `none\|minimal\|low\|medium\|high\|xhigh`; пусто = дефолт |
| `inline` | нет | `auto` | **только для legacy-режима** (Приложение A). В companion-режиме игнорируется |
| `inline_files` | нет | — | **только для legacy-режима**. В companion-режиме игнорируется |

**Return** (как структурированный текст — контракт неизменен):

```
status: ok | timeout | disabled | error
output_file: <path>
task_id: <claude-code-bash-task-id>
duration_s: <число>
notes: <если есть проблемы>
```

`output_file` всегда содержит **финальное сообщение Codex** (в companion-режиме — поле `rawOutput`, извлечённое из `--json`). Вызывающий скилл читает именно этот файл.

---

## Алгоритм

### Шаг 1 — Парсинг args

Извлеки переменные из args. Валидация:
- `role` ∈ {reviewer, implementer}
- `task_file` существует (`Read` для проверки)
- `scope` непуст
- `timeout_min` > 0

При невалидных — return `status: error, notes: <причина>`.

---

### Шаг 2 — Kill-switch check

Прочитай `.claude/codex.json` и применить precedence matrix (env > file):

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

Если `FINAL=false` — return `status: disabled, notes: kill-switch active`.

---

### Шаг 3 — Резолв движка (companion vs legacy)

```bash
COMPANION=$(ls -d "$HOME"/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | sort -V | tail -1)
```

- `COMPANION` непуст и файл существует → **companion-режим** (Шаги 4–7 ниже).
- Иначе → **legacy-режим** (Приложение A). Залогируй `notes: companion not found, legacy codex exec`.

> Companion — это движок плагина `codex@openai-codex`. Он сопровождается OpenAI и использует app-server protocol, а не `codex exec` + bubblewrap. Путь резолвится по glob (версия в пути не хардкодится — переживает обновление плагина).

---

### Шаг 4 — Сборка prompt-файла

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

**Содержимое prompt-файла** (адаптируй под role). В companion-режиме Codex читает файлы через свои shell-tools штатно — **inline-вкладывание не нужно**:

```text
CONTEXT: WORKER
ROLE: <role>
ORCHESTRATOR: Claude Code в проекте Arbitra_support (SUP).

TASK_FILE: <task_file>
SPEC_FILE: <spec_file (или "не указан")>
WORKTREE: <worktree>
SCOPE: <scope>
LENS (для reviewer): <lens>

DO:
- Прочитай TASK_FILE, SPEC_FILE и AGENTS.md в корне.
- Выполни задачу строго в SCOPE.
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

Запиши через `Write` в `$PROMPT_FILE`.

---

### Шаг 5 — Сборка команды companion

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

**Env-проброс (venv в worktree, R3) — через реальную команду `env`, НЕ префикс-переменную.**
В bash `$PRE cmd` из раскрытия переменной **не** распознаёт `VAR=val` как assignment (проверено эмпирически) — поэтому собираем аргументы для `env`, а команду зовём напрямую (без строки `CMD` с фейковыми кавычками):

```bash
ENV_ARGS=""
[ -n "$VIRTUAL_ENV" ]            && ENV_ARGS="$ENV_ARGS PATH=$VIRTUAL_ENV/bin:$PATH VIRTUAL_ENV=$VIRTUAL_ENV"
[ -n "$PYTHONPATH" ]             && ENV_ARGS="$ENV_ARGS PYTHONPATH=$PYTHONPATH"
[ -n "$DJANGO_SETTINGS_MODULE" ] && ENV_ARGS="$ENV_ARGS DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE"
```

---

### Шаг 6 — Запуск в фоне + watchdog

Запусти через `Bash(run_in_background=true)`, перенаправив stdout в `$RAW_JSON`, stderr в `$ERR_FILE`:

```bash
env $ENV_ARGS node "$COMPANION" task --json $WT_FLAG $WRITE_FLAG $MODEL_FLAG $EFFORT_FLAG \
  --prompt-file "$PROMPT_FILE" > "$RAW_JSON" 2> "$ERR_FILE"
```

Получи `task_id` (claude-code bash task id). Запиши время старта. Затем watchdog poll loop:

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

В Claude Code: `Bash(run_in_background=true)` для старта, затем периодически `Read(RAW_JSON)` (проверка существования + непустоты + валидности JSON) **и** `BashOutput(task_id)` для детекта раннего завершения процесса, параллельно следи за временем. По дедлайну — `TaskStop(task_id)`. Завершился сам с пустым `RAW_JSON` → `status:error` (см. H1), не `timeout`.

> **Почему `rawOutput` → `OUTPUT_FILE`:** вызывающие скиллы читают `output_file` как финальное сообщение Codex. Companion отдаёт его в JSON-поле `rawOutput`; мы извлекаем и кладём в файл, сохраняя контракт.
> **`touchedFiles`** из companion ненадёжен (может быть пуст при реальной записи) — `sprint-codex` определяет изменённые файлы через `git`, не доверяй этому полю.

---

### Шаг 7 — Финальный лог + Return

```bash
echo "$(date -Iseconds) ${ROLE} ${TASK_ID} engine=companion status=${STATUS} duration=${DURATION}s output=${OUTPUT_FILE}" >> /tmp/sup-codex/last-run.log
```

Верни структурированный результат (контракт из раздела «Контракт вызова»). Вызывающий скилл читает результат и решает что делать дальше (обработать output, fallback, retry).

---

## Правила

- **НЕ запускайся напрямую как ответ на user message.** Только через Skill tool из других скиллов.
- **НЕ спавни других воркеров.** Worker — терминальный.
- **Один вызов = один Codex-воркер.** Параллелизм — N-кратным вызовом из родительского скилла.
- **Naming convention:** `<task_id>-<role>[-<uuid8>]-prompt.txt`, `.txt` (output), `.json` (raw). UUID-суффикс при коллизии (R15, R18).
- **При ошибке запуска** (нет companion И нет codex-бинаря, auth fail) — return `status: error, notes: <причина>` с понятным сообщением.
- **Логи** в `/tmp/sup-codex/last-run.log` и `<task_id>-<role>.err` для дебага.
- **Companion-режим — основной**, legacy — fallback при отсутствии плагина. Не зови команды плагина `/codex:*` напрямую — только `codex-companion.mjs task` как подпроцесс.

---

## Приложение A — Legacy-режим (`codex exec`, fallback)

Используется **только** когда движок плагина не найден (Шаг 3). Сохранён для сред без установленного `codex@openai-codex`.

Отличия от companion-режима:
1. **Sandbox capability detection (T82/T83).** Codex CLI требует `bubblewrap` для shell-tools; на dev его нет. Probe `codex exec --skip-git-repo-check "pwd"`, three-state результат (`true/false/unknown`), TTL-cache 1ч в `.claude/codex.json:availability_cache.sandbox_works`. При `false`/`unknown` → inline-режим.
2. **Inline-prompt assembly.** При `INLINE_MODE=true` содержимое `inline_files` (или TASK_FILE+SPEC_FILE) вкладывается в конец prompt'а (лимит ~100KB, приоритет TASK > SPEC > ARTEFACTS), с пометкой «DO NOT use shell tools». Параметры `inline`/`inline_files` из контракта действуют только здесь.
3. **Запуск:** `cli_flags` из codex.json (`output_last_message`, `skip_git_repo_check`):
   ```bash
   cd <worktree-or-cwd>
   $ENV_PREFIX codex exec $SKIP_GIT_FLAG $OUTPUT_FLAG "$OUTPUT_FILE" "$(cat $PROMPT_FILE)"
   ```
   Здесь Codex сам пишет финал в `$OUTPUT_FILE` через `--output-last-message` (JSON-парсинг не нужен).
4. **Watchdog** — тот же: `Bash(run_in_background)` → poll `OUTPUT_FILE` на непустоту → `TaskStop` по дедлайну.

Return-контракт идентичен. В `notes` указывай `engine=legacy`.
