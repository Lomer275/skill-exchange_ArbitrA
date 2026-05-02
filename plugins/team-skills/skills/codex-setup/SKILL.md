---
name: codex-setup
description: "Одноразовая установка и проверка Codex CLI для связки Claude × Codex. Создаёт AGENTS.md в корне репо и .claude/codex.json со всеми обязательными полями. Используй когда пользователь говорит '/codex-setup', 'поставь codex', 'установи codex cli', 'настрой codex', 'init codex', 'включи кодекс'. Скилл идемпотентен — повторный запуск обновляет cli_version с warning при расхождении."
---
# /codex-setup — Установка и проверка Codex CLI

Готовит окружение для связки Claude × Codex: ставит Codex CLI, создаёт `AGENTS.md` и `.claude/codex.json`, прогоняет smoke-тест.

**Идемпотентность:** повторный запуск не ломает state — обновляет `cli_version` с warning при расхождении, перезаписывает только AUTO-SYNCED блок в `AGENTS.md`.

---

## Алгоритм

### Шаг 1 — Старт-сообщение

В чат:

```
## /codex-setup — Старт

Phase 1 имплементация связки Claude × Codex (S11).
Шаги: проверка → установка → AGENTS.md → codex.json → smoke.
```

---

### Шаг 2 — Проверка существующей установки

```bash
command -v codex && codex --version
```

- **Если установлен** — Зафиксируй `EXISTING=true` и **переходи к Шагу 4** (пропустить только Шаг 3 «установка», верификацию флагов и auth НЕ пропускать — иначе идемпотентность ломается при переименовании флагов или удалении auth).
- **Если не установлен** — Шаг 3.

---

### Шаг 3 — Установка Codex CLI

**Перед установкой** — проверь актуальное имя пакета через `context7` MCP:

```
mcp__plugin_context7_context7__resolve-library-id "openai codex cli"
```

Если context7 недоступен или не дал ясного имени — fallback на `@openai/codex` (npm).

**Основной путь (npm):**
```bash
npm install -g @openai/codex
```

**Fallback (pipx):**
```bash
pipx install openai-codex
```

Если оба упали — STOP, сообщи пользователю причину (нет npm/pipx, no internet, no permissions).

**Логирование:**
```bash
mkdir -p /tmp/codex-orch
echo "$(date -Iseconds) install: <команда>" >> /tmp/codex-orch/setup.log
```

---

### Шаг 4 — Верификация флагов

```bash
# Sanitize: одна строка, без переносов, экранирование кавычек для безопасной записи в JSON.
CLI_VERSION=$(codex --version 2>&1 | head -n1 | tr -d '\n\r' | sed 's/"/\\"/g')
[ -z "$CLI_VERSION" ] && CLI_VERSION="unknown"
echo "$(date -Iseconds) version: ${CLI_VERSION}" >> /tmp/codex-orch/setup.log

# Извлекаем фактические имена флагов из help — не хардкодим.
HELP=$(codex exec --help 2>&1)
SKIP_FLAG=$(echo "$HELP" | grep -oE '\-\-skip-git-repo-check' | head -1)
OUTPUT_FLAG=$(echo "$HELP" | grep -oE '\-\-output-last-message' | head -1)

# Fallbacks (актуальные дефолты Codex CLI 0.x)
[ -z "$SKIP_FLAG" ]   && SKIP_FLAG="--skip-git-repo-check"
[ -z "$OUTPUT_FLAG" ] && OUTPUT_FLAG="--output-last-message"
```

- Переменные `$SKIP_FLAG` и `$OUTPUT_FLAG` **используются во всех последующих шагах** (smoke-тест, codex.json, фактические запуски). Не хардкодить имена.
- Если флаги не нашлись в help (Codex CLI поменял имена) — fallback оставит дефолты, но в чат идёт warning «WARN: <flag> не найден в codex exec --help — проверь актуальное имя».

---

### Шаг 4.4 — Проверка project trust в `~/.codex/config.toml`

Закрывает AC 3 (config.toml валиден, проект помечен `trusted`).

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

**Edge case:** если в config.toml уже есть блок `[projects."$REPO_ROOT"]` **без** `trust_level=trusted`, скрипт допишет ещё один блок ниже. TOML-валидаторы трактуют это как ошибку (duplicate table). Если на руках старый невалидный state — пользователю надо вручную мержить блоки. Этот edge case считаем редким (обычно user либо сам не правит config.toml, либо знает что делает); полноценный TOML-merge вынесен в follow-up.

В чат — короткое сообщение: «✅ Project trust: trusted».

---

### Шаг 4.5 — Верификация auth

Codex требует либо OpenAI API ключ, либо ChatGPT-аккаунт. Проверь:

```bash
ls -la ~/.codex/auth.json 2>/dev/null
```

**Если файл не существует** — нет auth. STOP с инструкцией:

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

**Если файл существует** — определи auth_mode и валидность:

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

В чат — короткое сообщение:
- `✅ Auth: <auth_mode>` (apikey/chatgpt) — без значения ключа.
- При warning — предложи `codex auth login` для перенастройки.

Лог:
```bash
echo "$(date -Iseconds) auth: ${AUTH_MODE}" >> /tmp/codex-orch/setup.log
```

**Не показывай ключ в чате** — даже фрагмент. Это secret.

---

### Шаг 5 — Создание/обновление `.claude/codex.json`

Прочитай существующий файл (если есть). Сравни `cli_version` со свежим `codex --version` — при расхождении предупреди.

Запиши/обнови:

```json
{
  "enabled": true,
  "disabled_reason": null,
  "disabled_at": null,
  "cli_version": "<вывод codex --version>",
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

Если файл существовал с `enabled: false` или `disabled_reason` — **сохрани** их (не сбрасывай на дефолты). Меняй только `cli_version` и `cli_flags`.

`availability_cache.checked_at: null` — форсируем перепроверку при первом routing-триггере. `sandbox_works` будет проставлен `codex-worker` после probe (T83 three-state probe: `true` / `false` / `null` если ещё не проверяли).

**Замечание (T83):** поле `session_id` удалено из схемы. Кэширование теперь TTL-only (1 час) — было обнаружено что `${CLAUDE_SESSION_ID}` env-переменной не существует в Claude Code, и привязка к session делала кэш одноразовым.

---

### Шаг 6 — Создание/обновление `AGENTS.md` в корне репо

Если `AGENTS.md` существует — найди блок между маркерами:

```
<!-- AUTO-SYNCED: BEGIN -->
...
<!-- AUTO-SYNCED: END -->
```

Перезапиши **только** этот блок. Если файла нет — создай с шаблоном ниже.

**Шаблон `AGENTS.md`:**

```markdown
# AGENTS.md — инструкции для Codex CLI воркеров

> Этот файл читается автоматически каждым `codex exec` запуском в проекте.
> Оркестратор — Claude Code; Codex выступает как узкоспециализированный воркер.

## Контекст проекта

- **Проект:** <название и краткое описание — заполни из CLAUDE.md>.
- **Стек:** <язык, фреймворк, БД, очереди, внешние интеграции>.
- **Главный документ:** [CLAUDE.md](CLAUDE.md) — читай его в первую очередь.

## Гайды (если в проекте есть)

- `docs/guides/doc_conventions.md` — правила именования файлов.
- `docs/guides/specifications_guide.md` — структура спек.
- `docs/guides/task_decomposition_guide.md` — структура задач.
- `docs/guides/versioning_guidelines.md` — SemVer + Conventional Commits.

## Запреты

Эти правила обязательны для всех Codex-воркеров:

1. **Не делать `git commit` или `git push`** — коммиты делает оркестратор Claude через `/safe-push`.
2. **Не трогать секреты:** `.env*`, `.servers`, любые токены/ключи.
3. **Не править `CHANGELOG.md` и `HANDOFF.md`** — это шаги `/accept` (оркестратор).
4. **Не лезть в `docs/tasks/Done/`** — там завершённые задачи, их трогать нельзя.
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

**Перезапись AUTO-SYNCED блока в существующем `AGENTS.md`:**

Используется Python — sed/awk на многострочном regex'е ненадёжны (закрывает L3 из ревью):

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

**Сборка AUTO-SYNCED блока:**

1. **Динамически найди memory-каталог** для текущего проекта:
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
2. Прочитай `$MEMORY_DIR/MEMORY.md` (это **индекс**, контент в отдельных .md файлах рядом).
3. Для каждой записи в индексе — открой соответствующий `.md` файл в **той же директории** `$MEMORY_DIR/`, прочитай его frontmatter (поле `type:`).
4. Если `type: feedback` — извлеки `name`, `description`, тело документа.
5. Сформируй markdown-список в AUTO-SYNCED блоке:
   ```markdown
   - **<name>:** <первая строка тела или description>
   ```
6. Если feedback-записей нет (или memory-каталог не найден) — оставь placeholder «Пока нет сохранённых feedback-предпочтений пользователя.»

---

### Шаг 7 — Smoke-тест

Использует `$SKIP_FLAG` из Шага 4 (а не хардкод — иначе при rename CLI-флага скилл сломается, см. C7 из ревью):

```bash
timeout 30 codex exec "$SKIP_FLAG" "echo ok"
```

- Прошёл за <30s — ✅ smoke ok.
- Не прошёл — диагностика (БЕЗ показа значений ключа):
  - `codex --version` — есть бинарь?
  - `jq -r '.auth_mode' ~/.codex/auth.json 2>/dev/null` — какой режим? (НЕ выводи `OPENAI_API_KEY` или токены — это секрет)
  - `jq -r 'has("OPENAI_API_KEY") or has("tokens")' ~/.codex/auth.json` — есть ли поле с креденшелами вообще?
  - Есть интернет (для API)?

Запиши в лог:
```bash
echo "$(date -Iseconds) smoke: <ok|fail: причина>" >> /tmp/codex-orch/setup.log
```

---

### Шаг 8 — Финальный отчёт

Выведи в чат:

```markdown
## /codex-setup — Готово

✅ **Codex CLI:** <версия>
✅ **Установка:** <команда> (или existing — если был установлен)
✅ **Auth:** <apikey | chatgpt> (только режим, без значений ключа)
✅ **Файлы созданы/обновлены:**
  - `.claude/codex.json` — все 6 полей
  - `AGENTS.md` (корень репо) — запреты + AUTO-SYNCED блок
  - `/tmp/codex-orch/setup.log` — лог установки
✅ **Smoke:** echo ok прошёл за <X>s
⚠️ **Предупреждения:** <если есть — расхождение версий, fallback на pipx, итд>

**Следующий шаг:** связка готова — попробуй `/codereview-dual <T-номер>` или `/codex-toggle status`.
```

---

## Правила

- **Идемпотентность обязательна:** повторный запуск не ломает state, не сбрасывает kill-switch.
- **AUTO-SYNCED блок** в AGENTS.md перезаписывается полностью при каждом запуске; остальной текст AGENTS.md сохраняется (пользователь мог дополнить).
- **При ошибке установки** — STOP с понятным сообщением, не оставляй полу-установленное состояние.
- **Имена флагов** в `cli_flags` — фактические из `codex exec --help`, не хардкод.
- **Версия Codex CLI меняется быстро** — при расхождении со старой `cli_version` warning, не блокировать.
- Логи — в `/tmp/codex-orch/setup.log` для дебага.
