---
name: codex-toggle
description: "Управление kill-switch'ем связки Claude × Codex. Включает/выключает связку без переустановки CLI и без потери конфигов. Используй когда пользователь говорит '/codex-toggle', '/codex-toggle on', '/codex-toggle off', '/codex-toggle status', 'выключи codex', 'включи codex', 'отключи кодекс', 'верни classic-режим',"
---
# /codex-toggle — Управление kill-switch'ем Codex

Включает/выключает связку Claude × Codex одной командой. **Не удаляет** Codex CLI и не трогает `~/.codex/`. Включить обратно — мгновенно.

---

## Подкоманды

- `/codex-toggle on` — включить Codex (routing уйдёт в dual/codex-варианты).
- `/codex-toggle off [причина]` — выключить (routing вернётся в classic).
- `/codex-toggle status` — показать текущее состояние.

Если подкоманда не передана — спросить пользователя или показать `status`.

---

## Алгоритм

### Если `.claude/codex.json` не существует

`/codex-setup` ещё не запускался. Сообщи:

```
❌ .claude/codex.json не найден. Сначала запусти /codex-setup для базовой инициализации.
```

STOP.

---

### `on`

```bash
# Прочитать текущее
ENABLED=$(jq -r '.enabled' .claude/codex.json)

# Обновить (T83: availability_cache как структурированный объект, не null — для consistency с codex-worker schema)
jq '.enabled = true | .disabled_reason = null | .disabled_at = null | .availability_cache = {"checked_at": null, "available": null, "sandbox_works": null}' \
  .claude/codex.json > .claude/codex.json.tmp && mv .claude/codex.json.tmp .claude/codex.json
```

В чат:
```
✅ Codex включён.
- enabled: true
- availability_cache очищен (форсируем перепроверку при следующем routing-триггере)
- env CODEX_ENABLED имеет приоритет над файлом, проверь shell

Routing теперь будет выбирать /codereview-dual и /sprint-codex когда Codex доступен.
```

---

### `off [причина]`

Парсинг причины: всё после `off` — текст причины (опционально).

```bash
REASON="${ARGS:-нет причины}"
NOW=$(date -Iseconds)

jq --arg r "$REASON" --arg t "$NOW" \
  '.enabled = false | .disabled_reason = $r | .disabled_at = $t | .availability_cache = {"checked_at": null, "available": null, "sandbox_works": null}' \
  .claude/codex.json > .claude/codex.json.tmp && mv .claude/codex.json.tmp .claude/codex.json
```

В чат:
```
🛑 Codex отключён.
- причина: <REASON>
- время: <NOW>
- routing уходит в classic (`/codereview`, `/sprint`)

Включить обратно — `/codex-toggle on`.
Codex CLI и AGENTS.md не тронуты.
```

---

### `status`

Прочитай все поля `.claude/codex.json`. Проверь:

- наличие `codex` бинаря в shell;
- env-переменную `CODEX_ENABLED`.

Выведи:

```markdown
## /codex-toggle status

**Файл:** .claude/codex.json
**enabled:** true | false
**disabled_reason:** <если выключен>
**disabled_at:** <если выключен>
**cli_version:** <версия>
**cli_flags:**
  - output_last_message: <флаг>
  - skip_git_repo_check: <флаг>
**availability_cache:**
  - checked_at: <ISO дата или null>
  - available: <true/false/null>
  - sandbox_works: <true/false/null> — работает ли bubblewrap sandbox (T83 three-state)

**Окружение:**
- `command -v codex`: <путь или "не найден">
- env CODEX_ENABLED: <значение или "не задана">

**Эффективное состояние:**
- Файл: <enabled>
- Env override: <yes/no>
- **Итог: Codex <включён/выключен>** — routing будет использовать <dual/classic>.
```

---

## Правила

- **НЕ удаляет** Codex CLI, не трогает `~/.codex/`, не удаляет AGENTS.md или новые скиллы.
- `availability_cache` обнуляется при любом `on/off` — форсируем перепроверку.
- При `off` без причины — записать `"нет причины"` (не пусто).
- Имя `disabled_reason` хранится в человеческом виде (русская строка ок).
- Дата `disabled_at` — ISO 8601.
- При невалидном JSON в codex.json — STOP с сообщением «Файл повреждён, запусти `/codex-setup` ещё раз».
