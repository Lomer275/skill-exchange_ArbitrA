# Как пользоваться скиллами команды

Каталог из 16 общих Claude Code скиллов команды ArbitrA. Установка — одна команда в Claude Code, дальше работают автоматически.

## Установка (один раз)

В Claude Code (CLI или IDE-расширение):

```
/plugin marketplace add Lomer275/skill-exchange_ArbitrA
/plugin install team-skills@skill-exchange
```

Перезапусти Claude Code (полностью, не просто новый чат).

После этого все скиллы доступны как `/team-skills:<имя>`.

## Что внутри

| Скилл | Зачем |
|---|---|
| `codereview` | Многофазный код-ревью (критерии приёмки + adversarial + walkthrough + архитектура) |
| `codereview-dual` | То же, но две линзы — Claude + Codex параллельно |
| `codereview-dual-loop` | Цикл `dual → fix` до полной чистоты от CRITICAL/HIGH |
| `review-loop` | То же, но обычный ревью (без Codex) |
| `fix` | План + минимальные точечные фиксы из таблицы ревью |
| `visualcheck` | Анализ UI по скриншотам и/или коду — баги вёрстки/UX |
| `sprint` | Автономный прогон спецификации: имплементация → тесты → review → accept → push |
| `sprint-codex` | То же параллельно через Codex-воркеры в worktree |
| `accept` | Закрытие задачи — переносит в Done/, обновляет HANDOFF/CHANGELOG |
| `safe-push` | Безопасный commit + push с проверкой секретов и Conventional Commits |
| `spec-writer` | Создаёт скелет спеки/задачи/BR с правильной нумерацией |
| `init_dev` | Инициализирует структуру docs/ для нового проекта |
| `codex-setup` | Установка и настройка Codex CLI (для двойного ревью / параллельных воркеров) |
| `codex-toggle` | Включить/выключить связку Claude × Codex |
| `bitrix24-developer` | Generic-паттерны Bitrix24 REST API (CRM, smart-процессы, бизнес-процессы, disk, batch) |
| `n8n-workflow-manager` | Управление n8n workflows (search, edit, activate, execute) |

Полный каталог с описаниями — в [корневом README](../README.md).

## Как вызывать

**Прямой вызов:**

```
/team-skills:codereview
/team-skills:fix
/team-skills:sprint S05
```

**Естественным языком** — Claude сам активирует нужный скилл по триггер-фразе:

- «сделай ревью» → `codereview` (или `codereview-dual` если включён Codex)
- «исправь баги» → `fix`
- «закрой задачу T07» → `accept`
- «закоммить и запушь» → `safe-push`
- «прогони спринт S05» → `sprint`
- «проверь UI» → `visualcheck`

Триггер-фразы для каждого скилла перечислены в его `description` (видно в `/plugin list` или в `SKILL.md`).

## Обновления

Когда в репо появляются новые скиллы или фиксы:

```
/plugin update team-skills@skill-exchange
```

Перезапуск Claude Code.

## Скиллы с настройкой окружения

Два скилла работают «из коробки», но раскрывают весь потенциал только с конфигом твоего проекта:

- **`bitrix24-developer`** — скопируй [references/env.example.md](../plugins/team-skills/skills/bitrix24-developer/references/env.example.md) в свой репо как `BITRIX_ENV.md`, заполни Portal/Webhook/Funnels/Smart-процессы. **Не коммить заполненный файл с реальным WEBHOOK_TOKEN** — добавь в `.gitignore`.
- **`n8n-workflow-manager`** — аналогично, конкретный n8n-инстанс и креды храни в проектном конфиге, не в публичном репо.

## Связка Claude × Codex (опционально)

Скиллы `codereview-dual`, `codereview-dual-loop`, `sprint-codex` требуют установленного [Codex CLI](https://github.com/openai/codex) с активной авторизацией. Поставить и проверить:

```
/team-skills:codex-setup
```

Если Codex не нужен — `/team-skills:codex-toggle off` отключает routing в dual-варианты, остаются обычные `/team-skills:codereview` и `/team-skills:sprint`.

## Если что-то не работает

- **Скилл не появился после `/plugin install`** → перезапусти Claude Code полностью (не просто `/clear`).
- **Не нашло скилл по имени** → проверь полное имя: `/plugin list` покажет установленные плагины и их скиллы.
- **Marketplace не подключается** → `/plugin marketplace list`, проверь что `Lomer275/skill-exchange_ArbitrA` в списке.
- **`/plugin` не отвечает** → команда работает в Claude Code TUI и IDE-расширении (VS Code/JetBrains). В обёртках/прокси может не работать — открой стандартный `claude` CLI.

## Контрибуция

Хочешь добавить свой скилл или поправить существующий — см. [CONTRIBUTING.md](../CONTRIBUTING.md).

Кратко:

```bash
git clone https://github.com/Lomer275/skill-exchange_ArbitrA.git
cd skill-exchange_ArbitrA
python cli/skill_exchange.py setup-hooks
python cli/skill_exchange.py new my-skill-name
# редактируешь plugins/team-skills/skills/my-skill-name/{SKILL.md, meta.json, README.md}
git add plugins/team-skills/skills/my-skill-name
git commit -m "feat(skills): add my-skill-name"
git push
```

Pre-commit hook сам валидирует и обновит каталог `index.json` + корневой `README.md`. Для прав на push — запроси collaborator у Кости (@Lomer275).
