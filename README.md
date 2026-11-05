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
| [accept](plugins/team-skills/skills/accept/README.md) | kostya | workflow, documentation | Закрывает задачу в документации по обязательному профилю .claude/team-skills.json: статусы в задаче, спеке и хендоффе, запись в журнале, перенос в настроенный каталог завершённых задач. Без коммита и push. |
| [agents-context](plugins/team-skills/skills/agents-context/README.md) | Костя | agents, codex, setup, context | Раскладывает общий контекст команды по обоим агентам — Claude Code и Codex. Собственный одноимённый навык проекта или пользователя имеет приоритет. |
| [auto-pilot](plugins/team-skills/skills/auto-pilot/README.md) | kostya | autopilot, orchestration, cron, telegram, workflow, automation | Автопилот для репозиториев с профилем team-skills и установленными скриптами: выбирает одно действие, проверяет результат и оставляет изменения на ревью. TG-уведомления, бюджет и git-guard; без автоматических коммитов, пушей и PR. |
| [bitrix24-developer](plugins/team-skills/skills/bitrix24-developer/README.md) | kostya | bitrix24, crm, api | Паттерны Bitrix24 REST API с обязательным порядком согласования записи: песочница, маршрут проекта или явное подтверждение; константы домена, воронок и типов относятся к порталу express-bankrot.ru. Собственный одноимённый навык проекта или пользователя имеет приоритет. |
| [close](plugins/team-skills/skills/close/README.md) | kostya | workflow, context, housekeeping | Завершает сессию: сохраняет проверенный контекст и статусы по профилю .claude/team-skills.json, собирает повторы, готовит коммит и убирает временные файлы. Коммит и push — только с отдельным явным согласием на файлы и действие. Парный к /intro. |
| [codereview](plugins/team-skills/skills/codereview/README.md) | kostya | code-review, quality | Многофазный придирчивый код-ревью задачи: критерии приёмки + adversarial + user walkthrough + архитектурный fit. Только анализ, без фиксов. Собственный одноимённый навык имеет приоритет. |
| [codereview-dual](plugins/team-skills/skills/codereview-dual/README.md) | kostya | code-review, codex, quality | Двойной независимый код-ревью: Claude + Codex параллельно, мерж findings в одну severity-ranked таблицу с метками [both]/[claude]/[codex]. Явная модель Codex: аргументы → конфиг проекта → gpt-6-luna/medium. Собственный одноимённый навык имеет приоритет. |
| [codereview-dual-loop](plugins/team-skills/skills/codereview-dual-loop/README.md) | kostya | code-review, codex, fix, automation | Цикл /codereview-dual → /fix до полной чистоты от CRITICAL и HIGH. Принудительный dual (Claude + Codex) на каждой итерации, максимум 5 итераций. При недоступности Codex — graceful fallback на /review-loop. Явная модель Codex: аргументы → конфиг проекта → gpt-6-luna/medium. Собственный одноимённый навык имеет приоритет. |
| [codex-setup](plugins/team-skills/skills/codex-setup/README.md) | kostya | codex, bootstrap | Одноразовая установка и проверка Codex CLI для связки Claude × Codex. Создаёт AGENTS.md и .claude/codex.json. Идемпотентен. Явная модель Codex: аргументы → конфиг проекта → gpt-6-luna/medium. Собственный одноимённый навык имеет приоритет. |
| [codex-toggle](plugins/team-skills/skills/codex-toggle/README.md) | kostya | codex, config | Управление kill-switch'ем связки Claude × Codex. on / off [причина] / status. Собственный одноимённый навык имеет приоритет. |
| [codex-worker](plugins/team-skills/skills/codex-worker/README.md) | kostya | internal, codex, helper | Внутренний помощник для запуска Codex-воркера. Вызывается только из навыков team-skills с явными аргументами. Принимает файл задачи либо разовый brief_file (путь /impl). Движок выбирается по ЗДОРОВЬЮ, а не по наличию: плагин codex@openai-codex несёт свой движок, который может быть старше глобального CLI и молча возвращать пустой результат — тогда воркер уходит на legacy codex exec (обязательно с < /dev/null, иначе CLI ждёт EOF на stdin и висит до таймаута). Явная модель Codex: аргументы → конфиг проекта → gpt-6-luna/medium. |
| [dashboards](plugins/team-skills/skills/dashboards/README.md) | kostya | dashboards, observability, ui, data-sources, review | Принципы надёжных дашбордов: происхождение и свежесть чисел, пустые состояния, темы, доступ и владелец. Источники данных и сетевые ограничения определяются по документации текущего проекта; профиль необязателен. |
| [env-audit](plugins/team-skills/skills/env-audit/README.md) | Костя | audit, onboarding, agents, secrets, resources, process, architecture | Приёмка рабочего места: коллектор фактов + бриф до 20 КБ + справочники по темам. Одиннадцать регламентов, секреты и 1Password, сеть, расход токенов и связка с Codex, архитектура проектов, знакомство с человеком. Клинап применяется только после показанного диффа и «да», запись HANDOFF и CHANGELOG проверяется по факту в песочнице; в финале — отчёт и инструкция человеку. Собственный одноимённый навык проекта или пользователя имеет приоритет. |
| [example-skill](plugins/team-skills/skills/example-skill/README.md) | team | example, template | Демонстрационный скилл — шаблон для создания своих. Собственный одноимённый навык проекта или пользователя имеет приоритет. |
| [fix](plugins/team-skills/skills/fix/README.md) | kostya | code-review, fix, quality | Планирование и применение фиксов по findings из ревью или визуальной проверки. План строит Claude и ждёт подтверждения; правки исполняемого кода делегируются Codex-воркеру, дифф Claude сверяет с планом. CRITICAL → HIGH → MEDIUM, минимальные точечные изменения. Явная модель Codex: аргументы → конфиг проекта → gpt-6-luna/medium. Собственный одноимённый навык имеет приоритет. |
| [impl](plugins/team-skills/skills/impl/README.md) | kostya | codex, workflow, delegation, core | Точка входа режима «Claude думает — Codex программирует». Делегирует написание кода Codex-имплементеру для правки по запросу, файл задачи не нужен: Claude находит код и пишет бриф, Codex реализует, Claude читает дифф и гоняет тесты. Без него делегирование существует только внутри /sprint-codex и /codereview-dual. Явная модель Codex: аргументы → конфиг проекта → gpt-6-luna/medium. Собственный одноимённый навык имеет приоритет. Требует enabled=true в .claude/codex.json; иначе останавливается. |
| [init_dev](plugins/team-skills/skills/init_dev/README.md) | kostya | bootstrap, documentation, workflow | Создаёт структуру документации, architecture, HANDOFF, CHANGELOG, CLAUDE.md и профиль .claude/team-skills.json по выбранному префиксу. Копирует гайды только при наличии источника. |
| [intro](plugins/team-skills/skills/intro/README.md) | kostya | workflow, context | Загружает контекст по обязательному профилю .claude/team-skills.json: хендофф, журнал, открытые задачи и состояние git. Показывает следующий шаг, блокеры и расхождения. Только чтение; парный к /close. |
| [n8n-workflow-manager](plugins/team-skills/skills/n8n-workflow-manager/README.md) | kostya | n8n, automation, workflow | Управление n8n workflows: поиск, чтение, создание, правка, активация и выполнение; для записи в Bitrix — песочница, маршрут проекта или явное подтверждение. Собственный одноимённый навык проекта или пользователя имеет приоритет. |
| [review-loop](plugins/team-skills/skills/review-loop/README.md) | kostya | code-review, fix, automation | Цикл codereview → fix до полной чистоты от CRITICAL и HIGH. Максимум 5 итераций; досрочный стоп, когда фиксы ходят по кругу. Собственный одноимённый навык имеет приоритет. |
| [safe-push](plugins/team-skills/skills/safe-push/README.md) | kostya | git, safety | Безопасный commit + push с блокирующей проверкой секретов и форматом Conventional Commits. Не делает force push без явной просьбы и не коммитит в ветку деплоя (обычно main). Собственный одноимённый навык имеет приоритет. Commit и push требуют подтверждения конкретных файлов и действий; просьба только о commit не разрешает push. |
| [spec-brainstorm](plugins/team-skills/skills/spec-brainstorm/README.md) | kostya | spec, brainstorm, workflow, interactive | Помогает сформулировать новую спецификацию через вопросы: проблема, цель, архитектура, риски и DoD. Требует профиль .claude/team-skills.json; финальную запись делегирует команде commands.spec_writer после подтверждения черновика человеком. |
| [spec-writer](plugins/team-skills/skills/spec-writer/README.md) | kostya | documentation, spec, workflow | Создаёт спецификации (S), задачи (T) и бизнес-требования (BR) по обязательному профилю .claude/team-skills.json и гайдам проекта. Один вызов — один файл, только скелет. |
| [sprint](plugins/team-skills/skills/sprint/README.md) | kostya | workflow, automation, spec | Выполняет задачи спецификации волнами: реализация, тесты и review-loop. Требует профиль team-skills; --yes готовит изменения до ready to commit, коммит и пуш только по явному согласию в чате. |
| [sprint-codex](plugins/team-skills/skills/sprint-codex/README.md) | kostya | workflow, codex, parallel | Параллельный спринт через Codex-воркеры в git worktree. Drop-in замена /sprint для волн ≥2 задач. Явная модель Codex: аргументы → конфиг проекта → gpt-6-luna/medium. Собственный одноимённый навык имеет приоритет. Требует профиль проекта; коммиты, merge и очистка волны — только после подтверждения человека. |
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
