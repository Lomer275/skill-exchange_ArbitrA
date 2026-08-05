# Skill Exchange ArbitrA

Внутренняя библиотека Claude Code скиллов команды ArbitrA.
Распространяется как Claude Code marketplace.

## Установка (рекомендованный путь)

В Claude Code:

```
/plugin marketplace add Lomer275/skill-exchange_ArbitrA
/plugin install team-skills@skill-exchange
```

После установки все скиллы доступны как `/team-skills:<имя-скилла>`.

## Альтернатива: личная установка одного скилла через CLI

```bash
git clone https://github.com/Lomer275/skill-exchange_ArbitrA.git
cd skill-exchange_ArbitrA
python cli/skill_exchange.py install <имя-скилла>
```

Копирует `SKILL.md` в `~/.claude/skills/<имя>/`. Скилл доступен как `/<имя>`.

## Каталог скиллов

| Имя | Автор | Теги | Описание |
|-----|-------|------|----------|
| [accept](plugins/team-skills/skills/accept/README.md) | kostya | workflow, documentation | Закрывает задачу: помечает done в файле/спеке/HANDOFF, добавляет в CHANGELOG, переносит в Done/. Адаптируется к префиксу проекта. |
| [agents-context](plugins/team-skills/skills/agents-context/README.md) | Костя | agents, codex, setup, context | Раскладывает общий контекст команды по обоим агентам — Claude Code и Codex |
| [auto-pilot](plugins/team-skills/skills/auto-pilot/README.md) | kostya | autopilot, orchestration, cron, telegram, workflow, automation | Continuous-mode autopilot для проектов с SUP-конвенциями: cron-headless оркестратор который сам выбирает следующее действие (Rule 1-6), self-heal на budget exhaustion, TG control plane (inline-buttons + slash-commands), git-guard на destructive ops. Включает SKILL.md, 10 helper-скриптов, JSON-schema для config и install.sh для setup. |
| [bitrix24-developer](plugins/team-skills/skills/bitrix24-developer/README.md) | kostya | bitrix24, crm, api | Generic-набор паттернов работы с Bitrix24 REST API: CRM, smart processes, business processes, disk, batch API, n8n integration. |
| [close](plugins/team-skills/skills/close/README.md) | kostya | workflow, context, housekeeping | Завершает рабочую сессию одной командой: харвест повторов в навыки, фиксация контекста (хендофф + память агента + статусы задач ПО ФАКТУ), карточка эффективности ярусов AI, секрет-скан и подготовка коммита дня, уборка временного мусора. Парный к /intro. Источник — кокпит Алексея, версия адаптирована под конвенции SUP. |
| [codereview](plugins/team-skills/skills/codereview/README.md) | kostya | code-review, quality | Многофазный придирчивый код-ревью задачи: критерии приёмки + adversarial + user walkthrough + архитектурный fit. Только анализ, без фиксов. |
| [codereview-dual](plugins/team-skills/skills/codereview-dual/README.md) | kostya | code-review, codex, quality | Двойной независимый код-ревью: Claude + Codex параллельно, мерж findings в одну severity-ranked таблицу с метками [both]/[claude]/[codex]. |
| [codereview-dual-loop](plugins/team-skills/skills/codereview-dual-loop/README.md) | kostya | code-review, codex, fix, automation | Цикл /codereview-dual → /fix до полной чистоты от CRITICAL и HIGH. Принудительный dual (Claude + Codex) на каждой итерации, максимум 5 итераций. При недоступности Codex — graceful fallback на /review-loop. |
| [codex-setup](plugins/team-skills/skills/codex-setup/README.md) | kostya | codex, bootstrap | Одноразовая установка и проверка Codex CLI для связки Claude × Codex. Создаёт AGENTS.md и .claude/codex.json. Идемпотентен. |
| [codex-toggle](plugins/team-skills/skills/codex-toggle/README.md) | kostya | codex, config | Управление kill-switch'ем связки Claude × Codex. on / off [причина] / status. |
| [codex-worker](plugins/team-skills/skills/codex-worker/README.md) | kostya | internal, codex, helper | Internal helper для запуска Codex-воркера. Вызывается из /impl, /fix, /codereview-dual и /sprint-codex. Принимает файл задачи либо разовый brief_file (путь /impl). Движок выбирается по ЗДОРОВЬЮ, а не по наличию: плагин codex@openai-codex несёт свой движок, который может быть старше глобального CLI и молча возвращать пустой результат — тогда воркер уходит на legacy codex exec (обязательно с < /dev/null, иначе CLI ждёт EOF на stdin и висит до таймаута). |
| [example-skill](plugins/team-skills/skills/example-skill/README.md) | team | example, template | Демонстрационный скилл — шаблон для создания своих |
| [fix](plugins/team-skills/skills/fix/README.md) | kostya | code-review, fix, quality | Планирование и применение фиксов по findings из ревью или визуальной проверки. План строит Claude и ждёт подтверждения; правки исполняемого кода делегируются Codex-воркеру, дифф Claude сверяет с планом. CRITICAL → HIGH → MEDIUM, минимальные точечные изменения. |
| [impl](plugins/team-skills/skills/impl/README.md) | kostya | codex, workflow, delegation, core | Точка входа режима «Claude думает — Codex программирует». Делегирует написание кода Codex-имплементеру для ЛЮБОЙ правки, файл задачи не нужен: Claude находит код и пишет бриф, Codex реализует, Claude читает дифф и гоняет тесты. Без него делегирование существует только внутри /sprint-codex и /codereview-dual. |
| [init_dev](plugins/team-skills/skills/init_dev/README.md) | kostya | bootstrap, documentation, workflow | Создаёт базовую структуру документации проекта: docs/, гайды, architecture.md, HANDOFF.md, CHANGELOG.md, CLAUDE.md. |
| [intro](plugins/team-skills/skills/intro/README.md) | kostya | workflow, context | Загружает контекст проекта в начале сессии — парный к /close. Читает хендофф (RESUME-PROMPT), открытые задачи и состояние git, выводит: где остановились, следующий шаг, открытые блокеры. Ловит расхождение хендоффа с репо и говорит о нём прямо. Ничего не меняет — только читает. |
| [n8n-workflow-manager](plugins/team-skills/skills/n8n-workflow-manager/README.md) | kostya | n8n, automation, workflow | Управление n8n workflows: search, inspect, create, edit, активация, выполнение. Шаблоны нод, паттерны интеграций. |
| [review-loop](plugins/team-skills/skills/review-loop/README.md) | kostya | code-review, fix, automation | Цикл codereview → fix до полной чистоты от CRITICAL и HIGH. Максимум 5 итераций. |
| [safe-push](plugins/team-skills/skills/safe-push/README.md) | kostya | git, safety | Безопасный commit + push с блокирующей проверкой секретов и форматом Conventional Commits. Не делает force push без явной просьбы. |
| [spec-brainstorm](plugins/team-skills/skills/spec-brainstorm/README.md) | kostya | spec, brainstorm, workflow, interactive | Интерактивное со-создание новой SUP-спецификации в режиме «вопрос-ответ». Проводит через структурированную разведку (проблема → цель → фазы → архитектура → DoD), затем делегирует финальную запись файла в /spec-writer. Принципиально интерактивный — задаёт вопросы по одному через AskUserQuestion, не пишет файл пока человек не финализировал. |
| [spec-writer](plugins/team-skills/skills/spec-writer/README.md) | kostya | documentation, spec, workflow | Создаёт документы проекта: спецификации (S), задачи (T), бизнес-требования (BR). Один вызов = один файл, только скелет. |
| [sprint](plugins/team-skills/skills/sprint/README.md) | kostya | workflow, automation, spec | Автономно выполняет все задачи спецификации: имплементация → тесты → review-loop → accept → push. Поддерживает --dry-run и --yes (headless mode для cron-автопилота с check_authz из HANDOFF YAML, TG-ask retry-loop). |
| [sprint-codex](plugins/team-skills/skills/sprint-codex/README.md) | kostya | workflow, codex, parallel | Параллельный спринт через Codex-воркеры в git worktree. Drop-in замена /sprint для волн ≥2 задач. |
| [visualcheck](plugins/team-skills/skills/visualcheck/README.md) | kostya | ui, design, quality | Визуальная проверка UI по скриншотам или коду: баги вёрстки, UX-проблемы, несоответствия дизайну. Анализ desktop+mobile. |

## Добавить свой скилл

```bash
python cli/skill_exchange.py new my-skill-name
# Отредактируй plugins/team-skills/skills/my-skill-name/{SKILL.md,meta.json,README.md}
git add plugins/team-skills/skills/my-skill-name
git commit -m 'feat: add my-skill-name'
git push
```

Подробнее: [CONTRIBUTING.md](CONTRIBUTING.md)

> _Этот файл авто-генерируется pre-commit hook'ом. Не редактируй вручную._
