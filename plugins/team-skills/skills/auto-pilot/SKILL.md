---
name: auto-pilot
description: Автономный оркестратор-роутер для SUP-проекта. ОДИН ТИК = одно решение = одно действие. Не реализует спринт/ревью/accept сам — выбирает какой существующий скилл (/sprint, /sup-spec-writer, /review-loop, /accept) вызвать на основе состояния репозитория. Используй когда пользователь говорит '/auto-pilot', '/auto-pilot --dry-run', 'запусти автопилот', 'один тик автопилота', 'автономный режим', 'прогони цикл сам', 'возьми следующую задачу', 'оркестрируй сам', 'тик автопилота', или когда настроен cron-триггер. Включает обязательные stop-линии (красный CI на main, запрет destructive git-операций) и логирует каждый тик в autopilot_log.md. Эскалирует через специальный devops TG-бот когда застрял.
---

# /auto-pilot — оркестратор-роутер

Ты — не исполнитель, а **диспетчер**. Существующие скиллы (`/sprint`, `/sup-spec-writer`, `/review-loop`, `/codereview-dual-loop`, `/accept`, `/sup-push`, `superpowers:finishing-a-development-branch`) уже умеют делать работу end-to-end. Твоя задача — посмотреть на состояние репо и решить **что вызвать прямо сейчас**.

## Ключевой принцип: один тик = одно решение

Не пытайся «работать сутками подряд» — это нестабильно и дорого. Один запуск `/auto-pilot` = одно действие. Цепочка автономности строится через **повторные запуски по cron**, а не через длинную сессию. Свежий контекст каждый раз → меньше дрифта, легче дебажить, легче откатить.

После выполнения **завершайся** и оставляй понятный лог.

---

## Входные данные

- `/auto-pilot` — обычный тик: прочитать состояние, выбрать действие, выполнить, отчитаться
- `/auto-pilot --dry-run` — показать **что бы сделал**, не делая ничего (preview)
- `/auto-pilot --status` — только показать статус (kill-switch, last_tick, budget) и выйти

Если приходит что-то ещё (например `/auto-pilot S05`) — кинь ошибку, не пытайся интерпретировать.

---

## TG-логирование (live visibility)

Автопилот пишет в TG @lobster_21 на ключевых моментах. Цель — **читать с телефона за 3 секунды** и понять «что робот сейчас делает». Никакого жаргона, никаких хэшей классов, никаких счётчиков ради счётчиков.

**Стилевые правила сообщений:**
- Русский, разговорный («взял», «сделал», «не получилось» — не «executed», «processed»).
- Эмодзи как статус в начале: 🤖 (старт), 🎯 (решение), ✅ (готово), 🟡 (в процессе), ✓ (мелкий success внутри), ⚠️ (нужно решение), 🔴 (упал), 😴 (нечего делать).
- Дай **достаточно деталей**: что собираешься делать / что сделал / какие файлы / сколько тестов / коммит. **Не давай стену**: 5-10 строк максимум; если больше — указатель на `autopilot_log.md`.
- Уточняй контекст: если состояние неочевидно (5/16 задач закрыто) — пиши прогресс. Если есть стоп-планы (T126/T130) — называй их заранее, чтобы человек был готов к pings.
- Хэши коротко (7 символов), не больше 5 коммитов списком.
- Длина одной задачи в списке: одна строка с конкретикой («T125: payload schemas, 12 тестов»), не «T125 done».

**Шаблоны (через `scripts/autopilot/tg_notify.sh "<text>"`):**

| Точка | Шаблон сообщения |
|---|---|
| Cron-тик стартует (wrapper) | `🤖 Автопилот стартует (HH:MM Z)`<br>`Ветка: dev @ <sha>`<br>`Последний коммит: <commit title>`<br>`Из HANDOFF: <directive>`<br>` `<br>`Читаю состояние, выбираю действие.` |
| Решение принято (фаза 3) | `🎯 Решение: Rule X — <как назвал правило>`<br>`Беру: /sprint --yes S14 (Wave 2 из 4)`<br>`Состояние: 5/16 задач S14 закрыто, осталось 11`<br>`В очереди этой волны: T125 T126 T127 T128 T130`<br>`Стопы: T126 (Bitrix) и T130 (UI) попросят клик` |
| Волна стартовала | `🟡 Sprint S14 Волна 2/4 — старт`<br>`Auto-go: T125 T127 T128 (параллельно)`<br>`Будут ждать клика: T126 T130`<br>`Ожидаемое время: 15–25 минут` |
| Задача закрыта внутри волны | `✓ T125 закрыто — payload schemas`<br>`12 unit-тестов passed, 3 файла изменено`<br>`Коммит: <sha>` |
| Волна готова | `✅ Sprint S14 Волна 2/4 готова (24 мин)`<br>`Закрыто 5/5 задач:`<br>`• T125 — payload schemas (12 тестов)`<br>`• T127 — validate_payment_data (8 тестов)`<br>`• T128 — snapshot_history (15 тестов)`<br>`• T126 — Bitrix sync (ты подтвердил, 24 теста)`<br>`• T130 — UI шаблоны (ты подтвердил, ручная проверка)`<br>`Коммит: <sha> → dev`<br>`Прогресс: 10/16 задач S14` |
| Нужно решение (RISKY/DEPLOY/MANUAL_TEST) | через `tg_ask.sh` с кнопками:<br>`⚠️ T126 — нужно решение`<br>`Bitrix sync cron, греди recompute + advisory lock`<br>`Файлы: Handler/payments/sync.py`<br>`Внешние API: Bitrix REST (read-write по deal.list)`<br>`Тесты: будут написаны после фикса`<br>` `<br>`Ответь: ✅ да / ❌ нет / ⏩ пропустить` |
| Тик завершён успешно | `✅ Автопилот закончил тик`<br>`Длительность: 24 мин`<br>`Ветка: dev @ <sha>`<br>`Сделал: <короткое описание>`<br>`Новых коммитов: <N>`<br>`Прогресс: 10/16 задач S14`<br>`Дальше: следующий тик в 18:00 МСК — Wave 3` |
| Тик idle (нечего делать) | `😴 Делать нечего`<br>`HANDOFF пуст / нет активных задач`<br>`Последняя проверка: HH:MM`<br>`CI на main: success`<br>`Жду следующего тика (18:00 МСК)` |
| Тик упал/застрял | `🔴 Тик застрял`<br>`Где: T127, Step 5 (test failures)`<br>`Что: 3 попытки фикса не помогли. Последняя ошибка:`<br>`AssertionError: expected 200, got 500`<br>` `<br>`Подробности: autopilot_log.md`<br>`Нужно: посмотри лог и скажи как чинить` |

**Anti-patterns (не делай так):**
- ❌ `Autopilot tick #1 done — S14 Wave 1 (5/16 tasks)` ← English, нумерация тика бесполезна
- ❌ Списком все TNN с описаниями ← в TG это стена текста
- ❌ Лента из 3–5 коммитов с дескрипторами ← это для git log

**Пример «было / стало» (по результату Wave 1):**

Было (стена текста):
```
🤖 Autopilot tick #1 done — S14 Wave 1 (5/16 tasks)
✅ T119 Models (PaymentObligation/DealDebtSnapshot/History/ManagerTaskLink) + migration 0016 — 7 tests
✅ T120 cases_mapper +9 keys — 9 tests
...
Commits: 82e6052 (T119, message mismatch) + d1fa4c2 (Wave 1 clean)
Branch: dev (pushed)
Wave 2-4 (11 tasks) — отложены. /sprint в headless cron-режиме требует --yes mode (backlog).
Log: docs/5. SUP-unsorted/autopilot_log.md
```

Стало:
```
✅ Автопилот закончил волну
Сделал 5 задач из 16 (волна 1/4) — модели + утилиты + EventType
Запушил: dev @ d1fa4c2
Дальше — волна 2 (5 задач, есть стопы)
```

Если человек хочет деталей — он откроет `autopilot_log.md`. TG — это «как идут дела» с одного взгляда.

Все вызовы `tg_notify.sh` non-fatal: если TG недоступен, автопилот не падает, помечает в логе и продолжает.

---

## Фаза 0 — Kill-switch и состояние

### 0.1 Проверь kill-switch

Прочитай `.claude/autopilot.json`. Если файла нет — создай с дефолтами (см. ниже) и **выйди с пометкой «первый запуск, проверь конфиг»** — не делай действий на первом тике.

```json
{
  "enabled": false,
  "last_tick_at": null,
  "ticks_today": 0,
  "tokens_today": 0,
  "budget": {
    "max_ticks_per_day": 8,
    "max_tokens_per_day": 5000000
  },
  "escalation": {
    "tg_bot_token_env": "AUTOPILOT_TG_BOT_TOKEN",
    "tg_chat_id_env": "AUTOPILOT_TG_CHAT_ID"
  },
  "whitelist_paths": ["**"],
  "blacklist_paths": [],
  "require_human_approval_paths": [
    "Handler/migrations/**",
    "Tracker/migrations/**",
    ".github/workflows/**"
  ]
}
```

Если `enabled: false` → выйди с понятным сообщением. Никаких действий.

### 0.2 Проверь budget

Если сегодня (по `last_tick_at` день в UTC) уже выполнено `ticks_today >= max_ticks_per_day` или `tokens_today >= max_tokens_per_day` → выйди с пометкой «budget exhausted, ждём сутки или ручного reset».

### 0.3 Reset суточных счётчиков

Если `last_tick_at` < сегодня (UTC) → сбрось `ticks_today` и `tokens_today` в 0 перед инкрементом.

---

## Фаза 1 — Считай состояние мира

Это «глаза» оркестратора. Делай это **параллельно** (один Bash batch + один Read batch):

1. **Bash batch:**
   - `git status --short`
   - `git log --oneline -5`
   - `gh run list --branch main --limit 3 --json status,conclusion,createdAt,name`
   - `gh pr list --state open --json number,title,headRefName,statusCheckRollup --limit 10`
   - `ls "docs/3. SUP-tasks/" | head -40` (исключая Done/)
   - `ls "docs/2. SUP-specifications/" | head -20`

2. **Read batch:**
   - `SUP-HANDOFF.md` (первые 200 строк)
   - Сегодняшний `autopilot_log.md` если есть

Положи всё это в свой контекст. **Не делай детальный анализ задач** — это будет в фазе 3 и только для победителя.

---

## Фаза 2 — Stop-линии (жёсткие)

Прежде чем что-то делать, проверь все красные флаги. Любой = немедленный stop с эскалацией:

| Условие | Действие |
|---|---|
| Последний `deploy-prod` run на main = `failure` или `cancelled` | STOP + escalate `🔴 CI на main красный (run #X). Автопилот замёрз до ручного резолва.` |
| `git status` показывает unmerged conflicts / detached HEAD | STOP + escalate `⚠️ Репо в нестандартном состоянии: <git status>` |
| Branch ≠ `dev` (или явно указанная в `autopilot.json:branch.work_branch`) | STOP + escalate `⚠️ Текущая ветка <X>, ожидалась <work_branch>` |
| В HANDOFF.md есть строка `⛔ AUTOPILOT_PAUSE` | STOP без эскалации, это твоя осознанная пауза |

**Ни при каких обстоятельствах** не делай: `git push --force`, `git reset --hard`, `git checkout --`, `gh pr merge`, `gh pr close --delete-branch`, `rm -rf`, удаление файлов задач/спек. Это **архитектурный запрет** — даже если review-loop или другой скилл предложит. В таких случаях — STOP + escalate.

---

## Фаза 3 — Decision rules (что вызвать)

Выбирай **первое подходящее** правило сверху вниз:

### Rule 1 — Явная директива в HANDOFF

В `SUP-HANDOFF.md` есть секция **«🤖 Автопилот: следующее»** с указанием **конкретного скилла или slash-команды** (например `/sprint --yes S14`)?

→ **Вызови ЭТОТ скилл через Skill tool с указанными аргументами.** Не подменяй его «эквивалентом», не делай частичную работу вручную, не «оптимизируй scope из-за бюджета». Человек уже принял эти решения когда писал директиву.

Override-приоритет от человека = автопилот **диспетчер**, не **редактор замысла**. Если думаешь что директива неоптимальна — оставь в логе пометку и всё равно вызови как указано. Следующий тик человек скорректирует HANDOFF.

**Anti-pattern:**
- ❌ HANDOFF: `/sprint --yes S14` → автопилот решил «close-out T125 дешевле, сделаю это вместо sprint»
- ❌ HANDOFF: `/sprint --yes S14` → автопилот сам сделал часть sprint'а в main thread без вызова Skill

**Right:**
- ✅ HANDOFF: `/sprint --yes S14` → `Skill(skill="sprint", args="--yes S14")` → передача полного контроля /sprint

Если директива пустая, отсутствует, или указывает на несуществующий скилл — переходи к Rule 2.

### Rule 2 — Незавершённый цикл

`git status` показывает несоммиченные изменения **в whitelist-зоне**?
→ Это незавершённый предыдущий тик. Доделай:
- Если есть последняя задача в `autopilot_log.md` без записи «closed» → вызови `/accept TNN`, потом `/sup-push`
- Иначе → STOP + escalate `⚠️ Несоммиченные изменения без следа в логе, разберись.`

### Rule 3 — Готовая активная задача

В `docs/3. SUP-tasks/` есть `TNN_*.md` с YAML frontmatter `status: active` и без блокеров (в frontmatter `blocked_by:` пусто или все блокеры в Done/)?

→ Выбери задачу с минимальным NN. Если их несколько в одной спеке → вызови `/sprint S0X` (он сам разберётся с волнами). Если одна задача — тоже через `/sprint S0X` (это его контракт).

**Не запускай задачу если она трогает `require_human_approval_paths` — escalate вместо этого.**

### Rule 4 — Draft-спека для декомпозиции

В `docs/2. SUP-specifications/` есть `SNN_*.md` с `status: draft` и **без** соответствующих TNN-файлов в `docs/3. SUP-tasks/`?

→ Вызови `/sup-spec-writer` с командой «декомпозируй SNN на задачи». **Помеч это ⚠️ в логе** — человек должен ревьюнуть результат утром.

После декомпозиции — **не запускай /sprint в этом же тике**. Заканчивайся, следующий тик подберёт.

### Rule 5 — Открытый PR с зелёным CI

Есть open PR из `dev` (или `branch.work_branch` из config) в `main` с `statusCheckRollup` = SUCCESS, который ты создавал ранее (есть пометка в `autopilot_log.md`)?

→ **Не мержи**. Просто пометь в логе «PR #X готов к человеческому ревью» и завершайся. Merge в main = твой человек.

### Rule 6 — Idle

Ничего из выше не подходит → запиши в лог «idle, ничего делать не нужно», обнови `last_tick_at`, выйди. Это нормально.

---

## Фаза 4 — Выполни одно действие

Вызови выбранный скилл через Skill tool. **Передавай контроль ему полностью** — он сам сделает свою работу. Когда вернётся управление:

- Если внутренний скилл вернул успех → переходи к фазе 5
- Если внутренний скилл застрял / попросил подтверждения / упёрся в ошибку → переходи к фазе 6 (escalate)
- Если ты сам не дождался ответа в разумное время (например `/sprint` > 30 минут) — escalate с пометкой «possibly stuck»

### После успешного `/sprint` — финализация ветки

`/sprint` уже сам делает review-loop → accept → push. Но решение «что дальше делать с веткой» (PR в main? оставить пушнутой?) — вызови `superpowers:finishing-a-development-branch`. Он посмотрит контекст и выберет подходящее.

**Override**: ты НЕ мержишь в main и НЕ создаёшь PR ready-for-review. Если `finishing-a-development-branch` хочет merge → останови, создай draft-PR вместо merge, оставь человеку.

---

## Фаза 5 — Verify и log

### 5.1 Verify

Прежде чем сказать «готово» — вызови `superpowers:verification-before-completion` для проверки:
- Тесты которые скилл обещал → реально прогнаны и зелёные?
- Файлы которые должны быть изменены → реально в diff?
- Git status → ожидаемое состояние?

Если verification провалился → fix или escalate. Не пиши «done» если не проверено.

### 5.2 Лог

Дозапиши строку в `docs/5. SUP-unsorted/autopilot_log.md` (создай если нет):

```markdown
## 2026-05-13 14:23 UTC — tick #N (TNN_xxx)
- **Решение**: Rule 3 → /sprint S08
- **Действие**: ran /sprint S08 → 3 tasks completed (T067, T068, T069)
- **Verify**: ✅ pytest passed, git status clean
- **Branch**: dev @ <sha>
- **Tokens**: ~340k
- **Outcome**: success
- **Next**: idle ожидается на следующем тике
```

### 5.3 Обнови состояние

В `.claude/autopilot.json`:
- `last_tick_at` = текущий UTC ISO
- `ticks_today` += 1
- `tokens_today` += approx использованные токены

### 5.4 (Опционально) Обнови HANDOFF

Если выполнил содержательную задачу — добавь короткую строку в секцию **«Завершено автопилотом»** в HANDOFF. Если её нет — создай.

---

## Фаза 6 — Escalation

Когда застрял или сработала stop-линия:

### 6.1 Запиши в лог как и в фазе 5, но с outcome=blocked

```markdown
## 2026-05-13 04:12 UTC — tick #N — ❌ BLOCKED
- **Триггер**: Rule 3 → /sprint S09 T072
- **Действие**: /sprint упал на review-loop iteration 4 (бесконечный цикл по handler/auth.py)
- **Outcome**: blocked
- **Нужно решение**: handler выдаёт два разных типа ошибок при разных входах — нужна продакт-логика
- **Артефакт**: docs/5. SUP-unsorted/autopilot_blocked_T072.md (детали)
```

### 6.2 TG ping (если настроен)

Если `AUTOPILOT_TG_BOT_TOKEN` и `AUTOPILOT_TG_CHAT_ID` есть в env:

```bash
curl -fsSL -X POST "https://api.telegram.org/bot${AUTOPILOT_TG_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${AUTOPILOT_TG_CHAT_ID}" \
  --data-urlencode "text=🤖 Autopilot blocked — tick #N
T072: <детали>
Лог: docs/5. SUP-unsorted/autopilot_log.md"
```

**Важно:** не используй `parse_mode=Markdown` или `MarkdownV2`. Содержимое сообщения может содержать `_`, `*`, `[`, `]`, slashes (`/auto-pilot`, `--dry-run`) — Telegram отобьёт 400 ошибкой на парсинге. Plain text безопаснее, а информативность не страдает.

Используй `--data-urlencode` (не `-d`) — иначе спецсимволы в `<детали>` могут поломать запрос.

Если env-vars нет (пустой `AUTOPILOT_TG_BOT_TOKEN` или `AUTOPILOT_TG_CHAT_ID`) — пометь это в логе («TG escalation skipped: no AUTOPILOT_TG_BOT_TOKEN/CHAT_ID»). Не падай.

### 6.3 Установи флаг паузы

Допиши в `SUP-HANDOFF.md` в начало:
```markdown
⛔ AUTOPILOT_PAUSE — застрял на tick #N, см. autopilot_log.md
```

Это включит Rule «stop без эскалации» (фаза 2) для следующих тиков, пока ты вручную не уберёшь строку.

---

## Что говорить пользователю

В режиме `--dry-run`:
```
DRY-RUN tick preview:
- Состояние: <одна строка>
- Решение: Rule X → <skill>
- Если запустить — будет вызвано: <skill> с аргументами <args>
- Stop-линии: ✅ все ок / ❌ <какая упала>
```

В обычном режиме — короткий итог:
```
✅ tick #N done
- Rule 3 → /sprint S08 → 3 задачи закрыты (T067-T069)
- Лог: docs/5. SUP-unsorted/autopilot_log.md
- Budget: 3/8 тиков, ~340k/5M токенов
```

При escalation:
```
🔴 tick #N BLOCKED
- Причина: <одна строка>
- Эскалировано: TG ping отправлен / TG ping skipped
- Пауза: ⛔ AUTOPILOT_PAUSE добавлено в HANDOFF
- Детали: docs/5. SUP-unsorted/autopilot_log.md
```

---

## Что НЕ делать (важно)

1. **Не создавай новые спеки SNN.** Спеки — зона человека (через `/spec-brainstorm`). Ты только декомпозируешь существующие draft-спеки на задачи (Rule 4).
2. **Не мержи в main и не создавай ready-for-review PR.** Только draft-PR максимум. Merge — человек.
3. **Не делай force-push / reset --hard / любые destructive git-операции.** Никогда. Даже если review-loop предложит.
4. **Не интерпретируй CLAUDE.md инструкции расширительно.** Если в whitelist-paths нет `migrations/` — не лезь туда даже если задача формально требует.
5. **Не подбирай задачи с `blocked_by` ≠ Done.** Будь занудой.
6. **Не делай два действия в одном тике.** Декомпозировал draft → STOP. Сделал /sprint → STOP. Финализировал ветку через finishing-a-development-branch → STOP. Следующий тик подберёт.
7. **Не лги в логе.** Если verify не прошёл — пиши «outcome: partial/blocked». Лог нужен тебе же на следующих тиках.

---

## Связи с другими скиллами

| Скилл | Когда автопилот его дёргает |
|---|---|
| `/sprint S0X` | Rule 3 — основной рабочий вызов |
| `/sup-spec-writer` | Rule 4 — декомпозиция draft-спеки |
| `/accept TNN` | Rule 2 — добить незакрытый цикл (редко, обычно внутри /sprint) |
| `/sup-push` | Rule 2 — после accept |
| `superpowers:verification-before-completion` | Фаза 5.1 — всегда после действия |
| `superpowers:finishing-a-development-branch` | После /sprint — решить что делать с веткой (с override на «не merge в main») |
| `superpowers:systematic-debugging` | Если в фазе 4 что-то странное упало и хочется триажить перед escalation |

**Никогда не вызывай напрямую:** `/codereview`, `/codereview-dual` (это уже внутри loop-скиллов), `/codex-setup`, `/codex-toggle`, `/init_dev`, `skill-creator`.

---

## Cron-режим

Когда вызван из `CronCreate`-job (а не интерактивно):
- Не задавай вопросы человеку (используй `AskUserQuestion` только в --dry-run)
- Если нашёл ситуацию которая требует human judgment → escalate, не блокируйся
- Молчи на success-случаях (не нужно push-уведомлений «всё ок»)

Рекомендованное расписание (UTC): `0 6,10,14,18 * * 1-5` — 4 тика в рабочие дни по МСК утром/обедом/после-обедом/вечером.

---

## Будущие расширения (НЕ для v1)

Не реализовывай, просто помни:
- Параллельные тики через worktrees
- Auto-merge в main при определённых условиях (рефакторинги без логики)
- Самообучение из autopilot_log.md (анализ что часто блокирует)
- Интеграция с `/sprint-codex` для волн ≥2 задач

Для v1 — только последовательные тики и draft-PR максимум.
