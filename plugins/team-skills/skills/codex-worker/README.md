# codex-worker

Внутренний помощник для запуска одного Codex-воркера. **Не вызывается пользователем напрямую** — только из скиллов team-skills с явными аргументами (`/codereview-dual`, `/sprint-codex`) через Skill tool.

Формирует prompt-файл и запускает Codex. Основной путь — через движок плагина `codex@openai-codex` (`codex-companion.mjs task`, app-server runtime, без зависимости от bubblewrap); при отсутствии плагина — graceful fallback на legacy `codex exec` (Приложение A).

- **Args:** `role`, `task_file`, `scope`, `lens`, `worktree`, `timeout_min`, `task_id`, `model`, `effort`, …
- **Return:** `status` (ok/timeout/disabled/error), `output_file`, `task_id`, `duration_s`, `model`, `effort`, `notes`.
- Проверяет kill-switch (`.claude/codex.json` + `SUP_CODEX_ENABLED`), watchdog через `TaskStop`.

Часть спеки S11 (Claude × Codex orchestration), Phase 2.

> **Зависимость:** companion-режиму нужен установленный плагин `codex@openai-codex`
> (`/plugin marketplace add openai/codex-plugin-cc`). Без него воркер работает в legacy-режиме.

Явная модель Codex: аргументы → конфиг проекта → gpt-6-luna/medium.
