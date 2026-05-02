---
name: codereview-dual
description: "Двойной независимый код-ревью: параллельно запускает Codex-ревьюера в фоне и свои собственные фазы (acceptance criteria + adversarial), затем мержит findings в одну severity-ranked таблицу с пометками [both]/[claude]/[codex]. Output совместим с /fix и /review-loop. Используй когда пользователь говорит '/codereview-dual', 'двойной ревью', 'ревью с codex', 'две линзы', 'ревью с кодексом', или когда routing решил dual-режим (Codex доступен и enabled). При недоступности"
---
# /codereview-dual — Параллельный двойной код-ревью с Codex

Запускает Codex-ревьюера и Claude-ревьюера параллельно, мержит findings в один отчёт. Drop-in замена `/codereview` — output совместим с `/fix` и `/review-loop`.

---

## Входные данные

- `/codereview-dual` — задача определяется автоматически из `*HANDOFF.md` (первая 🟡)
- `/codereview-dual T17` — явный номер задачи

Если ничего не передано и в HANDOFF нет 🟡 — попроси у пользователя.

---

## Алгоритм

### Шаг 0 — Routing checks (kill-switch + availability)

#### 0.1 — Kill-switch

Прочитай `.claude/codex.json`:

```bash
ENABLED=$(jq -r '.enabled' .claude/codex.json)
ENV_VAL="${CODEX_ENABLED:-}"
case "$ENV_VAL" in
  true|1|yes)   FINAL=true ;;
  false|0|no)   FINAL=false ;;
  "")           FINAL=$ENABLED ;;
  *)            FINAL=$ENABLED ;;
esac
```

Если `FINAL=false` — отказ старта:

```
❌ Codex отключён в .claude/codex.json (или через CODEX_ENABLED).
Используй /codereview напрямую или включи Codex через /codex-toggle on.
```

STOP. Не продолжай.

#### 0.2 — Availability cache

Прочитай `availability_cache` из `.claude/codex.json`:

- Получи текущий session_id Claude Code (через переменную среды `CLAUDE_SESSION_ID` или metadata; если недоступно — генерируй UUID на запуск).
- Сравни `availability_cache.session_id` и `checked_at`:
  - совпадает session_id И `checked_at` ≤ 1 час назад → используй cached `available`.
  - иначе → запусти проверку: `codex --version && timeout 10 codex exec --skip-git-repo-check "echo ok"`. Обнови `availability_cache`.

Если `available=false` — graceful fallback на single-review (см. Шаг 5 fallback).

---

### Шаг 1 — Сбор контекста

1. Найти файл задачи: glob `docs/tasks/T<NN>_*.md` (или из HANDOFF).
2. Прочитать файл задачи: критерии приёмки, описание, затронутые файлы.
3. Определить путь спецификации (из строки `**Спецификация:**`).
4. Прочитать изменённые файлы кода (если перечислены или предоставлены).

Если код не предоставлен и в задаче не указан — попроси пользователя приложить.

---

### Шаг 2 — Параллельный старт Codex-ревьюера

В одном сообщении (без задержек):

```
Skill(skill="codex-worker", args="role=reviewer task_file=docs/tasks/T<NN>_<name>.md spec_file=docs/specifications/S<NN>_<name>.md scope=read-only lens=correctness,edge-cases,risks timeout_min=5 task_id=T<NN>")
```

**Линза Codex:** `correctness`, `edge-cases`, `risks` — **отличается от Claude'овской**, чтобы дать дополнительный сигнал.

Сохрани возвращённый `output_file` и `task_id`.

В чат:
```
🚀 Codex-ревьюер запущен в фоне (lens: correctness/edge-cases/risks).
Параллельно делаю свои фазы (A: критерии приёмки, B: adversarial).
```

---

### Шаг 3 — Свои фазы (параллельно во времени)

Сразу же (не дожидаясь Codex'а) выполни фазы из `/codereview`:

- **Фаза A — критерии приёмки:** для каждого пункта DoD задачи — найди в коде, вердикт ✅/❌/⚠️.
- **Фаза B — adversarial:** «Как этот код сломается?» Корректность, безопасность, контракт, производительность, dead code.
- **Фаза C — user walkthrough:** 3-5 сценариев (happy/empty/error/edge/concurrent).
- **Фаза D — архитектурный fit:** соответствие паттернам проекта.

Сформируй свою таблицу findings с колонками: `ID, Severity, Фаза, Файл:строка, Категория, Описание, Рекомендация`.

**Категории** (для матчинга): `acceptance-criteria`, `correctness`, `security`, `performance`, `style`, `dead-code`, `architecture`, `edge-case`.

---

### Шаг 4 — Сбор Codex output (poll)

После завершения своих фаз — `Read(output_file)` от codex-worker.

- Файл существует и непустой → парсим таблицу Codex'а.
- Файл пустой → poll каждые 2-3 сек до появления непустого, лимит — `timeout_min` (5 мин).
- Codex упал / `status: timeout|error` → fallback (Шаг 5).

**Парсинг таблицы Codex'а:** ожидаем markdown-таблицу с теми же колонками. Если формат другой — наивный парсинг по line-by-line, или fallback.

---

### Шаг 5 — Merge findings (или fallback)

#### 5a — Полноценный merge (Codex отдал результат)

**Алгоритм матчинга (R11):**

Для каждого finding из обоих источников — попарно сравнить с findings другого источника:

```python
def is_same(c, x):
    return (
        c.file_path == x.file_path
        and ranges_overlap(c.line_range, x.line_range)  # max(s1,s2) <= min(e1,e2)
        and c.category == x.category
    )
```

Если совпало:
- Описание = более информативное (длиннее по символам при равной информативности).
- Метка = `[both]`.
- **Severity disagreement (R13):**
  - Если severity разные — берём максимум (CRITICAL > HIGH > MEDIUM > LOW).
  - Метка расширяется: `[both, severity=max(claude=X, codex=Y)→Z]`.
  - При радикальном расхождении (CRITICAL↔LOW) — дополнительная метка `[severity-disputed]`.

Несовпавшие — `[claude]` или `[codex]` в зависимости от источника.

#### 5b — Fallback (Codex недоступен)

Если `availability_cache.available=false` или Codex вернул `status: timeout|error`:

В чат:
```
⚠️ Codex недоступен (<причина>). Делаю single-review (только Claude).
```

Используй только свои findings, в шапке таблицы — пометка `[fallback: claude-only, Codex недоступен: <причина>]`.

---

### Шаг 6 — Запись в файл задачи

В файл задачи (`docs/tasks/T<NN>_*.md`) добавь/обнови секцию:

```markdown
## Code Review (dual)

**Дата:** YYYY-MM-DD
**Ревьюеры:** Claude (фазы A/B/C/D), Codex (correctness/edge-cases/risks)
**Найдено:** N CRITICAL, M HIGH, K MEDIUM, L LOW
**Расхождения:** X [severity-disputed]

| ID | Severity | Фаза | Файл:строка | Описание | Рекомендация | Источник |
|----|----------|------|-------------|----------|--------------|----------|
| R1 | CRITICAL | B | ... | ... | ... | [both] |
| R2 | HIGH | A | ... | ... | ... | [claude] |
| R3 | HIGH | B | ... | ... | ... | [codex] |
| R4 | MEDIUM | C | ... | ... | ... | [both, severity=max(claude=LOW, codex=MEDIUM)→MEDIUM] |
```

Если секция уже была — добавь новую (не перезаписывай старые ревью), пометив датой.

---

### Шаг 7 — Финальный отчёт в чат

```markdown
## /codereview-dual — Готово

**Задача:** T<NN> — <название>
**Найдено:** N CRITICAL, M HIGH, K MEDIUM, L LOW
**Источники:** [both]: <число> | [claude]: <число> | [codex]: <число>
**Расхождения severity:** <число> [severity-disputed]

**Файл задачи обновлён:** docs/tasks/T<NN>_*.md (секция `## Code Review (dual)`)

**Следующий шаг:**
- Если есть CRITICAL/HIGH — запусти `/fix` или `/review-loop`.
- Если только MEDIUM/LOW — можно `/accept`.
```

---

## Правила

- **Routing — первый шаг.** Без kill-switch + availability проверки не стартуй.
- **Параллельность во времени, а не concurrency.** Codex стартует в фоне через `Skill("codex-worker", ...)`, Claude параллельно делает свои фазы, потом читает output Codex'а.
- **Линза Codex отличается от Claude.** Не дублируй покрытие — Claude берёт критерии+adversarial, Codex — корректность+edge-cases+risks.
- **Severity max при расхождении.** Адверсариально — выбираем худший случай.
- **Output совместим с /fix и /review-loop.** Колонка «Источник» — последняя; downstream-скиллы её игнорируют.
- **Fallback на single-review при недоступном Codex.** Не падай — деградируй с понятным сообщением.
- **Не пиши прямой git commit/push** — это `/safe-push`.
