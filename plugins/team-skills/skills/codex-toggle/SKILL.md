---
name: codex-toggle
description: >
  Manage the kill-switch for the Claude × Codex integration. Enables/disables the
  integration without reinstalling the CLI and without losing configs. Use when the user says
  "/codex-toggle", "/codex-toggle on", "/codex-toggle off", "/codex-toggle status",
  "выключи codex", "включи codex", "отключи кодекс", "верни classic-режим",
  "статус codex". Part of spec S11, Phase 5.
---

# /codex-toggle — Managing the Codex kill-switch

Enables/disables the Claude × Codex integration with a single command. **Does not delete** the Codex CLI and does not touch `~/.codex/`. Re-enabling is instant.

---

## Subcommands

- `/codex-toggle on` — enable Codex (routing will switch to dual/codex variants).
- `/codex-toggle off [reason]` — disable (routing reverts to classic).
- `/codex-toggle status` — show the current state.

If no subcommand is passed — ask the user or show `status`.

---

## Algorithm

### If `.claude/codex.json` does not exist

`/codex-setup` has not been run yet. Report:

```
❌ .claude/codex.json не найден. Сначала запусти /codex-setup для базовой инициализации.
```

STOP.

---

### `on`

```bash
# Read current state
ENABLED=$(jq -r '.enabled' .claude/codex.json)

# Update (T83: availability_cache as a structured object, not null — for consistency with the codex-worker schema)
jq '.enabled = true | .disabled_reason = null | .disabled_at = null | .availability_cache = {"checked_at": null, "available": null, "sandbox_works": null}' \
  .claude/codex.json > .claude/codex.json.tmp && mv .claude/codex.json.tmp .claude/codex.json
```

To chat:
```
✅ Codex включён.
- enabled: true
- availability_cache очищен (форсируем перепроверку при следующем routing-триггере)
- env SUP_CODEX_ENABLED имеет приоритет над файлом, проверь shell

Routing теперь будет выбирать /codereview-dual и /sprint-codex когда Codex доступен.
```

---

### `off [reason]`

Reason parsing: everything after `off` is the reason text (optional).

```bash
REASON="${ARGS:-нет причины}"
NOW=$(date -Iseconds)

jq --arg r "$REASON" --arg t "$NOW" \
  '.enabled = false | .disabled_reason = $r | .disabled_at = $t | .availability_cache = {"checked_at": null, "available": null, "sandbox_works": null}' \
  .claude/codex.json > .claude/codex.json.tmp && mv .claude/codex.json.tmp .claude/codex.json
```

To chat:
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

Read all fields of `.claude/codex.json`. Check:

- whether the `codex` binary is present in the shell;
- the `SUP_CODEX_ENABLED` env variable.

Output:

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
- env SUP_CODEX_ENABLED: <значение или "не задана">

**Эффективное состояние:**
- Файл: <enabled>
- Env override: <yes/no>
- **Итог: Codex <включён/выключен>** — routing будет использовать <dual/classic>.
```

---

## Rules

- **Does NOT delete** the Codex CLI, does not touch `~/.codex/`, does not delete AGENTS.md or new skills.
- `availability_cache` is reset on any `on/off` — we force a re-check.
- On `off` without a reason — write `"нет причины"` (not empty).
- The `disabled_reason` value is stored in human-readable form (a Russian string is fine).
- The `disabled_at` date is ISO 8601.
- On invalid JSON in codex.json — STOP with the message "Файл повреждён, запусти `/codex-setup` ещё раз".
