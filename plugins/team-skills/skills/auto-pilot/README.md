# Auto-Pilot Orchestrator

Автопилот для репозиториев с профилем team-skills и установленными скриптами, который выбирает следующее действие (Rule 1-6),
self-heal'ит budget exhaustion, управляется через TG inline-buttons + slash-commands,
и блокирует destructive git ops через git-guard.

## Когда использовать

Когда хочется чтобы кодеж двигался автономно по cron-расписанию, с TG-интерфейсом
для контроля. См. полный `description` в [SKILL.md](SKILL.md).

## Что делает (5-минутный обзор)

```
Trigger (cron 8:00 / 18:00 МСК ИЛИ /sprint в TG)
    ↓
run_tick.sh — wrapper с self-heal retry-loop (4 × $5 = $20 cap)
    ↓
claude --print "/auto-pilot" (Phase 0-6)
    ↓
Phase 0: kill-switch (.claude/autopilot.json:enabled)
Phase 1: read state (git, CI, HANDOFF, log)
Phase 2: stop-lines (CI red? AUTOPILOT_PAUSE? destructive op?)
Phase 3: decision (Rule 1: HANDOFF directive → /sprint / Rule 6: idle)
Phase 4: execute selected skill
Phase 5: verify + log
Phase 6: escalate если застрял
    ↓
Остановка: ready for review/commit / idle / pause / budget / ошибка
```

Параллельно работает:
- **heartbeat watchdog** (cron */2 min) — TG-ping на 5/15/25 мин, crash detection
- **TG listener daemon** — принимает `/status`, `/sprint S14`, `/pause`, `/enable`, ...
- **git-guard** — в тике разрешает `status`, `diff`, `log`, `show`, `rev-parse`, `ls-files`, `rev-list`, `merge-base`, `blame`, `cat-file`, `describe`, `for-each-ref`, `ls-tree`, `shortlog`, `grep`, `name-rev`, `show-ref`, `ls-remote`; просмотр `branch` (без аргументов, `--show-current`, `--list`, `-a`, `-r`, `-v`, `-vv`, `--contains`, `--merged`, `--no-merged`, последние три принимают ref), только `worktree list`, `remote` без аргументов/с `-v`, `remote show` (с `-n`), `remote get-url` (с `--push`/`--all`), `config --get/--get-all/--get-regexp/--list/-l`. Fetch разрешён без `--upload-pack` и `-u` (включая присоединённые значения и комбинации коротких опций). Остальные команды/формы, запись, неизвестные алиасы и ведущий `-c` блокируются кодом 100; ошибка конфига тоже означает отказ. Ведущие `-C`, `--git-dir`, `--work-tree`, `--no-pager`, `--paginate`, `--no-optional-locks` сохранены.

## Профиль и согласие человека

Собственный навык `auto-pilot` проекта или пользователя имеет приоритет. Этот используется при явном `/team-skills:auto-pilot` или отсутствии собственного.

До установки нужен `.claude/team-skills.json` версии 1 с `handoff`, `docs.specifications`, `docs.tasks`, `docs.tasks_done`, `docs.unsorted`, `commands.spec_writer`. Нет профиля/ключа — остановка с ошибкой. Формат: `team-skills:init_dev` и `docs/team-skills-profile.md` каталога. Пути относительны корню репозитория. Защищённые пути берутся из `.claude/autopilot.json:require_human_approval_paths`.

Тик заканчивается статусом `ready for review/commit`: список файлов, сообщение коммита, фактические проверки и уведомление TG, если настроено. Коммит, пуш, мерж, создание/мерж PR и удаление веток/worktree требуют явного «да» в этом чате на конкретное действие и файлы; согласие на коммит не разрешает пуш. `--yes`, cron, HANDOFF и TG-кнопки плана не дают такого разрешения. Тик не вызывает `/accept` и навыки финализации ветки.

`bypassPermissions` сохранён; PATH git-guard — единственный технический барьер Git в тике. Абсолютный путь к Git обходит PATH, поэтому обход запрещён инструкцией. `gh` гард не перехватывает: `gh pr create`, `gh pr merge` и другие операции записи в тике запрещены текстом навыка.

## Bootstrap (1 раз)

```bash
# В корне твоего проекта (git-репо):
./install.sh
```

Установщик спросит:
1. **AUTOPILOT_TG_BOT_TOKEN** — создай через [@BotFather](https://t.me/BotFather)
2. **AUTOPILOT_TG_ALLOWED_USERNAME** — твой `@username` в TG
3. Опционально: установить cron (08:00 + 18:00 МСК + heartbeat)
4. Опционально: запустить listener daemon в фоне

После — отправь `/start` боту → `/help` для меню.

## Day-to-day

| Команда в TG | Что делает |
|---|---|
| `/status` | Текущее состояние (тик, прогресс, последний коммит) |
| `/log [N]` | Последние N (1-5) записей из autopilot_log.md |
| `/enable` / `/disable` | Включить/выключить (без потери конфига) |
| `/pause [причина]` | Мягкая пауза (`⛔ AUTOPILOT_PAUSE` в HANDOFF) |
| `/resume` | Снять паузу |
| `/sprint S14` | Записать директиву в HANDOFF + запустить тик прямо сейчас |
| `/abort` | Убить активный тик (PID-scoped через group kill) |
| `/budget` | Счётчики дня + остаток бюджета |
| `/heartbeat` | Пнуть watchdog вручную |

## Файлы

```
.claude/autopilot.json           # State + budget + denylist
.env.dev                          # TG bot token + user_id (gitignored!)
<docs.unsorted>/autopilot_log.md  # Хронологический лог тиков

scripts/autopilot/
├── run_tick.sh                  # Wrapper continuous mode v4
├── heartbeat.sh                 # Watchdog (cron */2min)
├── tg_listener.py               # Daemon, sole getUpdates owner
├── tg_ask.sh                    # Send question + inline buttons
├── tg_wait_answer.sh            # Block until file-poll answer
├── tg_notify.sh                 # Plain send (Python urllib, token не в argv)
├── check_authz.py               # Parse HANDOFF YAML pre-auth
├── discover_chat_id.sh          # Setup helper для .env credentials
├── git-guard.sh                 # Technical block destructive git ops
└── path-overrides/git           # Symlink → git-guard.sh (PATH first)
```

## Safety

- `enabled=false` в JSON — kill-switch (cron-тики выходят на Phase 0)
- `⛔ AUTOPILOT_PAUSE` в HANDOFF — мягкая пауза без потери конфига
- В тике git-guard блокирует запись независимо от содержимого denylist; ошибка чтения конфига означает отказ
- Auth по numeric `user_id` (R2 codereview), username только для логов
- `--max-budget-usd 5` cap per attempt, 4 retry max = $20 на macro-tick
- `--permission-mode bypassPermissions` — required для cron-headless, но защищён git-guard и denylist в SKILL.md

## Troubleshooting

| Симптом | Где смотреть |
|---|---|
| Нет heartbeat'ов | `crontab -l` — heartbeat должен быть в списке. Логи: `logs/autopilot/heartbeat.log` |
| Listener мёртв | `pgrep -af tg_listener.py` — должен быть процесс. Рестарт: `setsid nohup python3 scripts/autopilot/tg_listener.py >> logs/autopilot/listener.log 2>&1 < /dev/null & disown` |
| TG-ask висит | Проверь listener живой + `/tmp/autopilot_answers/<msg_id>.json` создаётся при клике. Это новый "state-file pattern" — нет 409 conflict. |
| Тик не пишет в TG | `.env.dev` содержит `AUTOPILOT_TG_BOT_TOKEN` + `AUTOPILOT_TG_CHAT_ID`? Wrapper должен `set -a; source .env.dev; set +a` перед `claude --print`. |
| Wrapper "стартует" каждый cron но ничего не делает | Phase 0 — kill-switch (`enabled=false`) или Phase 2 — `AUTOPILOT_PAUSE` в HANDOFF. Снимай `/enable` + `/resume` в TG. |
