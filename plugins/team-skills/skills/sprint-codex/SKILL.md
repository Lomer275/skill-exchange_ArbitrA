---
name: sprint-codex
description: "Параллельный спринт через Codex-воркеры в git worktree. Читает спеку, строит волны по зависимостям, классифицирует волну (общий каталог vs worktree-per-task если задачи трогают shared/ или общие точки риска), запускает N Codex-имплементеров параллельно. После merge всей волны — делегирует ревью в /review-loop (НЕ зовёт /codereview-dual напрямую — иначе двойной ревью). Используй когда пользователь говорит '/sprint-codex', '/sprint-codex S05', 'параллельный спринт', 'спринт через кодекс', или когда routing решил sprint-codex (Codex доступен и волна ≥2 задач)."
---
# /sprint-codex — Параллельный спринт через Codex-воркеры

Drop-in замена `/sprint` для волн ≥2 задач. Codex-имплементеры работают параллельно в worktree, Claude оркестрирует merge → review-loop → accept → push.

---

## Входные данные

- `/sprint-codex S05` — обязательно номер спецификации.
- `/sprint-codex S05 --dry-run` — показать план волн без выполнения.

Если номер не передан — попроси у пользователя.

---

## Алгоритм

### Шаг 0 — Routing checks

Те же что в `/codereview-dual`:

1. **Kill-switch** (`.claude/codex.json:enabled` + env `CODEX_ENABLED` с precedence matrix). При выключенном — отказ старта с подсказкой включить через `/codex-toggle on` или предложить запустить classic `/sprint`.
2. **Availability cache.** Свежая проверка если кэш устарел.

При `available=false` — STOP с предложением `/sprint` (classic).

---

### Шаг 1 — Парсинг спеки

1. Прочитай `docs/specifications/S<NN>_*.md`.
2. Извлеки таблицу задач: `ID`, `Зависит от`, `Фаза`, `Статус`.
3. Для каждой draft-задачи прочитай файл (`docs/tasks/T<NN>_*.md`):
   - Acceptance criteria.
   - Затронутые файлы (из текста или explicit раздела).

---

### Шаг 2 — Построение волн (топологическая сортировка)

```python
def build_waves(tasks):
    waves = []
    completed = set(t.id for t in tasks if t.status == '✅')
    pending = [t for t in tasks if t.status != '✅']
    while pending:
        wave = [t for t in pending if all(d in completed for d in t.deps)]
        if not wave:
            raise CycleError("циклическая зависимость или non-completed deps")
        waves.append(wave)
        for t in wave:
            completed.add(t.id)
        pending = [t for t in pending if t not in wave]
    return waves
```

В чат: показать план волн.

```markdown
## /sprint-codex S<NN> — План

**Волн:** N
**Задач всего:** M

### Волна 1: <task-ids> (параллельно)
### Волна 2: ...
```

При `--dry-run` — STOP здесь.

---

### Шаг 3 — Цикл по волнам

Для каждой волны:

#### 3.1 — Классификация (общий каталог vs worktree)

Собери множество файлов для каждой задачи (из acceptance criteria + текущего кода через `git grep`/`find`).

**Правила:**
- Если множества **не пересекаются** И ни одна задача не трогает общие точки риска — общий каталог.
- Иначе — worktree per task.

**Общие точки риска:**
- `shared/` (любой файл).
- `tg_bot/texts.py`.
- `tg_bot/keyboards.py`.
- `Handler/models.py`.

В чат: «Волна N: <общий каталог|worktree-per-task>, причина: <...>».

#### 3.2 — Подготовка worktree (если нужно)

Для каждой задачи в волне:

```bash
WT_PATH="/tmp/codex-orch-wt/T${NN}-${SLUG}"
BRANCH="codex/T${NN}-${SLUG}"

# Collision check (R6)
if [ -e "$WT_PATH" ]; then
  TS=$(date +%s)
  mv "$WT_PATH" "${WT_PATH}.failed-${TS}"
  echo "⚠️ Existing worktree saved: ${WT_PATH}.failed-${TS}"
  # переименовать ветку если есть
  if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
    git branch -m "$BRANCH" "${BRANCH}-failed-${TS}"
  fi
fi

# Create fresh worktree
git worktree add "$WT_PATH" -b "$BRANCH"

# venv passthrough (R3): symlink если venv в репо
if [ -d "$(git rev-parse --show-toplevel)/.venv" ] && [ ! -e "$WT_PATH/.venv" ]; then
  ln -s "$(git rev-parse --show-toplevel)/.venv" "$WT_PATH/.venv"
fi
```

В чат для каждой задачи: «Создан worktree T<NN>: $WT_PATH».

#### 3.3 — Параллельный запуск Codex-воркеров

В **одном сообщении** (для реального параллелизма) делаем N вызовов:

```
Skill(skill="codex-worker", args="role=implementer task_file=docs/tasks/T<NN>_<name>.md spec_file=docs/specifications/S<NN>_<name>.md worktree=<WT_PATH-or-current> scope=edit:<paths> timeout_min=10 task_id=T<NN>")
```

Сохрани все task_id и output_file для каждого воркера.

В чат:
```
🚀 Волна N: запущено <K> Codex-воркеров параллельно.
```

#### 3.4 — Сбор результатов

Жди завершения всех воркеров. Параллельно `Read(output_file)` каждого. По завершении (или таймауту) — собери отчёты:

```markdown
**Волна N — Результаты:**
- T<NN1>: ✅ ok (<duration>s) — <краткий итог из output>
- T<NN2>: ⚠️ timeout — debug в /tmp/codex-orch-wt/T<NN2>-...failed-<ts>
- T<NN3>: ✅ ok (<duration>s) — ...
```

#### 3.5 — Merge ветками

Только для **успешных** воркеров. Последовательно:

```bash
cd <repo-root>
git merge "codex/T<NN>-<slug>"
```

При конфликте:
- Покажи `git status` пользователю.
- Спроси: «Разрешить вручную или откатить эту задачу?»
- Действуй по ответу.

При успехе merge:
```bash
git worktree remove "/tmp/codex-orch-wt/T<NN>-<slug>"
git branch -d "codex/T<NN>-<slug>"
```

Failed worktree-ы (с `.failed-<ts>`) **не удаляются** — остаются для дебага.

---

### Шаг 4 — После всех волн: ревью + accept + push

**ВАЖНО (R5):** не зови `/codereview-dual` напрямую. `/review-loop` сам через routing решит dual или single.

```
1. /review-loop  — для всех изменений пакетом
   └─ внутри он зовёт /codereview (через routing → /codereview-dual)
   └─ и /fix до чистоты от CRITICAL/HIGH

2. Для каждой задачи в волнах: /accept T<NN>

3. /safe-push  — один коммит на всю пачку (или по одному на задачу,
                спросить у пользователя в начале спринта)
```

---

### Шаг 5 — Cleanup

```bash
# Files older than 7 days в /tmp/codex-orch/
find /tmp/codex-orch -type f -mtime +7 -delete 2>/dev/null

# last-run.log сохраняем для дебага
```

---

### Шаг 6 — Финальный отчёт

```markdown
## /sprint-codex — Готово

**Спека:** S<NN>
**Волн обработано:** N
**Задач выполнено:** ✅ K | ⚠️ failed: M

### Per-task:
| ID | Статус | Duration | Worktree |
|----|--------|----------|----------|
| T77 | ✅ merged | 5m | (общий каталог) |
| T78 | ✅ merged | 8m | T78-<slug> (cleaned) |
| T79 | ⚠️ timeout | 10m | T79-<slug>.failed-<ts> (debug) |

### Review-loop: <чисто | N итераций, осталось MEDIUM/LOW>
### Accept: ✅ K задач
### Push: ✅ <commit hash> (или: коммит ожидает явного /safe-push)

**Failed задачи:** требуют ручного разбора. Debug-снимки в /tmp/codex-orch-wt/*.failed-*
```

---

## Правила

- **Routing — первый шаг.** Без kill-switch + availability проверки не стартуй.
- **Параллельность через `Bash(run_in_background=true)`** — N вызовов `Skill("codex-worker", ...)` в одном сообщении (не последовательно).
- **Worktree creation — последовательно** (избежать гонок), но воркеры внутри них — параллельно.
- **Collision check (R6) перед каждым `git worktree add`** — переименование занятого пути в `.failed-<ts>`.
- **venv passthrough (R3)** — симлинк `.venv` в worktree + env-переменные через `codex-worker`.
- **После merge — только `/review-loop`** (R5), без прямого `/codereview-dual`.
- **Failed worktree не удалять автоматически** — оставлять под `.failed-<ts>` для дебага.
- **Конфликты merge — интерактив с пользователем**, не автоматическое разрешение.
- **Cleanup `/tmp/codex-orch/` старше 7 дней** (R16) — на старте каждого спринта.
- При циклической зависимости в волнах — STOP с понятной ошибкой.
