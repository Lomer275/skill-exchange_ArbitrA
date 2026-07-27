---
name: codex-setup
description: >
  One-time installation and verification of the Codex CLI for the Claude × Codex
  pairing. Creates AGENTS.md in the repo root and .claude/codex.json with all
  required fields. Use when the user says "/codex-setup", "поставь codex",
  "установи codex cli", "настрой codex", "init codex", "включи кодекс". The skill
  is idempotent — a repeat run updates cli_version with a warning on mismatch.
  Part of spec S11 (docs/2. SUP-specifications/S11_claude_codex_orchestration_done.md), Phase 1.
---

# /codex-setup — Install and verify the Codex CLI

Prepares the environment for the Claude × Codex pairing: installs the Codex CLI, creates `AGENTS.md` and `.claude/codex.json`, runs a smoke test.

**Idempotency:** a repeat run does not break state — it updates `cli_version` with a warning on mismatch and overwrites only the AUTO-SYNCED block in `AGENTS.md`.

---

## Algorithm

### Step 1 — Start message

To chat:

```
## /codex-setup — Старт

Phase 1 имплементация связки Claude × Codex (S11).
Шаги: проверка → установка → AGENTS.md → codex.json → smoke.
```

---

### Step 2 — Check for an existing installation

```bash
command -v codex && codex --version
```

- **If installed** — set `EXISTING=true` and **go to Step 4** (skip only Step 3 "installation"; do NOT skip flag verification and auth — otherwise idempotency breaks when flags are renamed or auth is removed).
- **If not installed** — Step 3.

---

### Step 3 — Install the Codex CLI

**Before installing** — check the current package name via the `context7` MCP:

```
mcp__plugin_context7_context7__resolve-library-id "openai codex cli"
```

If context7 is unavailable or did not give a clear name — fall back to `@openai/codex` (npm).

**Primary path (npm):**
```bash
npm install -g @openai/codex
```

**Fallback (pipx):**
```bash
pipx install openai-codex
```

If both failed — STOP, tell the user the reason (no npm/pipx, no internet, no permissions).

**Logging:**
```bash
mkdir -p /tmp/sup-codex
echo "$(date -Iseconds) install: <команда>" >> /tmp/sup-codex/setup.log
```

---

### Step 4 — Flag verification

```bash
# Sanitize: одна строка, без переносов, экранирование кавычек для безопасной записи в JSON.
CLI_VERSION=$(codex --version 2>&1 | head -n1 | tr -d '\n\r' | sed 's/"/\\"/g')
[ -z "$CLI_VERSION" ] && CLI_VERSION="unknown"
echo "$(date -Iseconds) version: ${CLI_VERSION}" >> /tmp/sup-codex/setup.log

# Извлекаем фактические имена флагов из help — не хардкодим.
HELP=$(codex exec --help 2>&1)
SKIP_FLAG=$(echo "$HELP" | grep -oE '\-\-skip-git-repo-check' | head -1)
OUTPUT_FLAG=$(echo "$HELP" | grep -oE '\-\-output-last-message' | head -1)

# Fallbacks (актуальные дефолты Codex CLI 0.x)
[ -z "$SKIP_FLAG" ]   && SKIP_FLAG="--skip-git-repo-check"
[ -z "$OUTPUT_FLAG" ] && OUTPUT_FLAG="--output-last-message"
```

- The variables `$SKIP_FLAG` and `$OUTPUT_FLAG` are **used in all subsequent steps** (smoke test, codex.json, the actual runs). Do not hardcode the names.
- If the flags were not found in help (the Codex CLI changed the names) — the fallback keeps the defaults, but a warning goes to chat: "WARN: <flag> not found in codex exec --help — check the current name".

---

### Step 4.4 — Check project trust in `~/.codex/config.toml`

Closes AC 3 (config.toml is valid, the project is marked `trusted`).

```bash
REPO_ROOT="$(pwd)"
CONFIG_DIR="$HOME/.codex"
CONFIG_PATH="$CONFIG_DIR/config.toml"

# Создать каталог и файл если их нет (свежая система — codex auth login создаст auth.json, но не обязательно config.toml)
mkdir -p "$CONFIG_DIR"
touch "$CONFIG_PATH"

# Robust-проверка через awk: парсим TOML-блок [projects."<repo>"] до следующего [...] или EOF.
# Это устойчиво к произвольному порядку ключей внутри блока (в отличие от grep -A1).
HAS_TRUST=$(awk -v repo="$REPO_ROOT" '
  $0 == "[projects.\"" repo "\"]" { in_block = 1; next }
  /^\[/ && in_block { in_block = 0 }
  in_block && /^[[:space:]]*trust_level[[:space:]]*=[[:space:]]*"trusted"[[:space:]]*$/ { print "yes"; exit }
' "$CONFIG_PATH")

if [ -z "$HAS_TRUST" ]; then
  cat >> "$CONFIG_PATH" <<TOML

[projects."$REPO_ROOT"]
trust_level = "trusted"
TOML
  echo "✅ Добавлен trust_level=trusted для $REPO_ROOT в $CONFIG_PATH"
else
  echo "✅ Project trust already set: $REPO_ROOT"
fi
```

**Edge case:** if config.toml already has a `[projects."$REPO_ROOT"]` block **without** `trust_level=trusted`, the script will append another block below. TOML validators treat this as an error (duplicate table). If you have an old invalid state on hand, the user must merge the blocks manually. We consider this edge case rare (usually the user either does not edit config.toml themselves, or knows what they are doing); a full TOML merge is deferred to a follow-up.

To chat — a short message: "✅ Project trust: trusted".

---

### Step 4.5 — Auth verification

Codex requires either an OpenAI API key or a ChatGPT account. Check:

```bash
ls -la ~/.codex/auth.json 2>/dev/null
```

**If the file does not exist** — no auth. STOP with the instruction:

```
❌ Auth не настроен. Codex CLI установлен, но не сможет работать без авторизации.

Выбери один из вариантов и запусти команду:

  Вариант 1 — ChatGPT-аккаунт (рекомендуется при наличии Plus/Pro/Team):
    codex auth login
    (откроется браузер с OAuth-flow, использует квоту подписки)

  Вариант 2 — OpenAI API ключ (pay-as-you-go billing):
    codex auth login --api-key sk-proj-...
    (или вручную: записать ключ в ~/.codex/auth.json как
     {"auth_mode": "apikey", "OPENAI_API_KEY": "sk-..."})

После настройки auth — повторно запусти /codex-setup.
```

**If the file exists** — determine auth_mode and validity:

```bash
AUTH_MODE=$(jq -r '.auth_mode // "unknown"' ~/.codex/auth.json 2>/dev/null)
case "$AUTH_MODE" in
  apikey)
    HAS_KEY=$(jq -r '.OPENAI_API_KEY | length > 0' ~/.codex/auth.json)
    if [ "$HAS_KEY" != "true" ]; then
      echo "❌ STOP: auth_mode=apikey, но OPENAI_API_KEY пустой/отсутствует."
      echo "   Перенастрой: codex auth login --api-key sk-proj-... (или удали ~/.codex/auth.json и запусти codex auth login заново)"
      exit 1
    fi
    ;;
  chatgpt|oauth)
    HAS_TOKEN=$(jq -r '.tokens // empty | length > 0' ~/.codex/auth.json)
    if [ "$HAS_TOKEN" != "true" ]; then
      echo "❌ STOP: auth_mode=$AUTH_MODE, но tokens пустые/отсутствуют."
      echo "   Перенастрой: codex auth login (откроется браузер с OAuth-flow)"
      exit 1
    fi
    ;;
  *)
    echo "❌ STOP: неизвестный auth_mode '$AUTH_MODE' в ~/.codex/auth.json."
    echo "   Допустимые значения: apikey, chatgpt. Перенастрой через codex auth login."
    exit 1
    ;;
esac
```

To chat — a short message:
- `✅ Auth: <auth_mode>` (apikey/chatgpt) — without the key value.
- On a warning — suggest `codex auth login` to reconfigure.

Log:
```bash
echo "$(date -Iseconds) auth: ${AUTH_MODE}" >> /tmp/sup-codex/setup.log
```

**Do not show the key in chat** — not even a fragment. It is a secret.

---

### Step 5 — Create/update `.claude/codex.json`

Read the existing file (if any). Compare `cli_version` with the fresh `codex --version` — warn on a mismatch.

Write/update:

```json
{
  "enabled": true,
  "disabled_reason": null,
  "disabled_at": null,
  "cli_version": "<output of codex --version>",
  "cli_flags": {
    "output_last_message": "--output-last-message",
    "skip_git_repo_check": "--skip-git-repo-check"
  },
  "availability_cache": {
    "checked_at": null,
    "available": null,
    "sandbox_works": null
  }
}
```

If the file already existed with `enabled: false` or `disabled_reason` — **preserve** them (do not reset to defaults). Change only `cli_version` and `cli_flags`.

`availability_cache.checked_at: null` — forces a re-check on the first routing trigger. `sandbox_works` will be set by `codex-worker` after the probe (T83 three-state probe: `true` / `false` / `null` if not yet checked).

**Note (T83):** the `session_id` field was removed from the schema. Caching is now TTL-only (1 hour) — it was found that the `${CLAUDE_SESSION_ID}` env variable does not exist in Claude Code, and binding to the session made the cache single-use.

---

### Step 6 — Create/update `AGENTS.md` in the repo root

If `AGENTS.md` exists — find the block between the markers:

```
<!-- AUTO-SYNCED: BEGIN -->
...
<!-- AUTO-SYNCED: END -->
```

Overwrite **only** this block. If the file does not exist — create it with the template below.

**`AGENTS.md` template:**

```markdown
# AGENTS.md — инструкции для Codex CLI воркеров

> Этот файл читается автоматически каждым `codex exec` запуском в проекте Arbitra_support (SUP).
> Оркестратор — Claude Code; Codex выступает как узкоспециализированный воркер.

## Контекст проекта

- **Проект:** SupportBots (SUP) — AI-боты сопровождения клиентов по банкротству физических лиц.
- **Стек:** Python/Django, Aiogram 3.x (Telegram), MAX Platform SDK, PostgreSQL, Redis, Supabase, OpenAI API, Bitrix24.
- **Главный документ:** [CLAUDE.md](CLAUDE.md) — читай его в первую очередь.

## Гайды (читай по необходимости)

- [docs/4. SUP-guides/doc_conventions.md](docs/4.%20SUP-guides/doc_conventions.md) — правила именования файлов.
- [docs/4. SUP-guides/specifications_guide.md](docs/4.%20SUP-guides/specifications_guide.md) — структура спек.
- [docs/4. SUP-guides/task_decomposition_guide.md](docs/4.%20SUP-guides/task_decomposition_guide.md) — структура задач.
- [docs/4. SUP-guides/versioning_guidelines.md](docs/4.%20SUP-guides/versioning_guidelines.md) — SemVer + Conventional Commits.

## Запреты

Эти правила обязательны для всех Codex-воркеров:

1. **Не делать `git commit` или `git push`** — коммиты делает оркестратор Claude через `/sup-push`.
2. **Не трогать секреты:** `.env*`, `.servers`, любые токены/ключи.
3. **Не править `SUP-CHANGELOG.md` и `SUP-HANDOFF.md`** — это шаги `/accept` (оркестратор).
4. **Не лезть в `docs/3. SUP-tasks/Done/`** — там завершённые задачи, их трогать нельзя.
5. **Не спавнить других Codex-воркеров** — оркестрацию ведёт только Claude.
6. Использовать `python` из `$VIRTUAL_ENV/bin/python` для всех запусков (если работаешь в worktree).

## Стиль

- Документация — на **русском**.
- Технические комментарии в коде — на английском, минимально (только когда «почему», а не «что»).
- Текст коммита (если предлагаешь его в финальном отчёте) — Conventional Commits: `feat(scope): ...`, `fix(scope): ...`, `refactor(scope): ...`.

<!-- AUTO-SYNCED: BEGIN -->
## User feedback notes (auto-synced)

<!-- Этот блок генерируется /codex-setup из MEMORY.md (только feedback-type записи). -->
<!-- НЕ редактируй вручную — будет перезаписан при следующем /codex-setup. -->

<!-- placeholder: feedback memory entries будут вставлены сюда -->
<!-- AUTO-SYNCED: END -->
```

**Overwriting the AUTO-SYNCED block in an existing `AGENTS.md`:**

Python is used — sed/awk on a multi-line regex are unreliable (closes L3 from the review):

```python
python3 - <<'PY'
import re, pathlib

agents_path = pathlib.Path("AGENTS.md")
new_block = """## User feedback notes (auto-synced)

<!-- Этот блок генерируется /codex-setup из MEMORY.md (только feedback-type записи). -->
<!-- НЕ редактируй вручную — будет перезаписан при следующем /codex-setup. -->

{content}
"""  # content подставляется ниже из шагов сборки

if agents_path.exists():
    text = agents_path.read_text()
    # Заменяем блок между маркерами; флаг DOTALL чтобы захватить переносы строк.
    pattern = r'<!-- AUTO-SYNCED: BEGIN -->.*?<!-- AUTO-SYNCED: END -->'
    replacement = f'<!-- AUTO-SYNCED: BEGIN -->\n{new_block}\n<!-- AUTO-SYNCED: END -->'
    new_text, n = re.subn(pattern, replacement, text, flags=re.DOTALL)
    if n == 0:
        # Маркеров нет — append-им блок в конец
        new_text = text.rstrip() + '\n\n<!-- AUTO-SYNCED: BEGIN -->\n' + new_block + '\n<!-- AUTO-SYNCED: END -->\n'
    agents_path.write_text(new_text)
else:
    # Файла не было — создаём с полным шаблоном (см. ниже).
    pass  # обрабатывается в шаге 6
PY
```

**Building the AUTO-SYNCED block:**

1. **Dynamically find the memory directory** for the current project:
   ```bash
   REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
   REPO_NAME="$(basename "$REPO_ROOT")"
   # Claude Code хранит memory в ~/.claude/projects/<slug>/memory/, где slug = path с заменой '/' и '_' на '-'
   MEMORY_DIR="$(find ~/.claude/projects -maxdepth 1 -type d -iname "*${REPO_NAME//_/-}*" 2>/dev/null | head -1)/memory"
   if [ ! -d "$MEMORY_DIR" ]; then
     # Fallback: попытка по точному slug текущего пути
     SLUG="$(echo "$REPO_ROOT" | sed 's|^/||; s|/|-|g; s|_|-|g')"
     MEMORY_DIR="$HOME/.claude/projects/-${SLUG}/memory"
   fi
   if [ ! -d "$MEMORY_DIR" ]; then
     echo "WARN: memory-каталог не найден, AUTO-SYNCED блок останется пустым"
     # placeholder в AGENTS.md
   fi
   ```
2. Read `$MEMORY_DIR/MEMORY.md` (this is the **index**; the content is in separate .md files nearby).
3. For each entry in the index — open the corresponding `.md` file in the **same directory** `$MEMORY_DIR/`, read its frontmatter (the `type:` field).
4. If `type: feedback` — extract `name`, `description`, the document body.
5. Build a markdown list in the AUTO-SYNCED block:
   ```markdown
   - **<name>:** <first line of the body or description>
   ```
6. If there are no feedback entries (or the memory directory was not found) — leave the placeholder "Пока нет сохранённых feedback-предпочтений пользователя."

---

### Step 7 — Smoke test

Uses `$SKIP_FLAG` from Step 4 (not a hardcode — otherwise the skill breaks when the CLI flag is renamed, see C7 from the review):

```bash
timeout 30 codex exec "$SKIP_FLAG" "echo ok"
```

- Passed in <30s — ✅ smoke ok.
- Did not pass — diagnostics (WITHOUT showing the key values):
  - `codex --version` — is there a binary?
  - `jq -r '.auth_mode' ~/.codex/auth.json 2>/dev/null` — which mode? (do NOT print `OPENAI_API_KEY` or tokens — it is a secret)
  - `jq -r 'has("OPENAI_API_KEY") or has("tokens")' ~/.codex/auth.json` — is there a credentials field at all?
  - Is there internet (for the API)?

Write to the log:
```bash
echo "$(date -Iseconds) smoke: <ok|fail: причина>" >> /tmp/sup-codex/setup.log
```

---

### Step 8 — Final report

Output to chat:

```markdown
## /codex-setup — Готово

✅ **Codex CLI:** <версия>
✅ **Установка:** <команда> (или existing — если был установлен)
✅ **Auth:** <apikey | chatgpt> (только режим, без значений ключа)
✅ **Файлы созданы/обновлены:**
  - `.claude/codex.json` — все 6 полей
  - `AGENTS.md` (корень репо) — запреты + AUTO-SYNCED блок
  - `/tmp/sup-codex/setup.log` — лог установки
✅ **Smoke:** echo ok прошёл за <X>s
⚠️ **Предупреждения:** <если есть — расхождение версий, fallback на pipx, итд>

**Следующий шаг:** связка готова — попробуй `/codereview-dual <T-номер>` или `/codex-toggle status`.
```

---

## Rules

- **Idempotency is mandatory:** a repeat run does not break state and does not reset the kill-switch.
- **The AUTO-SYNCED block** in AGENTS.md is fully overwritten on every run; the rest of the AGENTS.md text is preserved (the user may have added to it).
- **On an installation error** — STOP with a clear message; do not leave a half-installed state.
- **The flag names** in `cli_flags` — the actual ones from `codex exec --help`, not a hardcode.
- **The Codex CLI version changes quickly** — on a mismatch with the old `cli_version`, warn, do not block.
- Logs — in `/tmp/sup-codex/setup.log` for debugging.
