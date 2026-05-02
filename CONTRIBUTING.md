# Contributing to Skill Exchange ArbitrA

Гайд по добавлению и обновлению Claude Code скиллов в команду.

## Требования

- Python 3.8+ (`python --version`)
- Git
- Claude Code (CLI или расширение VSCode/JetBrains)

## Как устроено распространение

Этот репо — **Claude Code marketplace**. Каждый скилл лежит в `plugins/team-skills/skills/<имя>/` и распространяется через встроенный механизм плагинов Claude Code.

Два пути установки:

| Путь | Кому | Команда | Доступ к скиллу |
|------|------|---------|-----------------|
| **Marketplace** (рекомендуется) | вся команда | `/plugin marketplace add Lomer275/skill-exchange_ArbitrA` → `/plugin install team-skills@skill-exchange` | `/team-skills:<имя>` |
| **CLI** (личная установка одного скилла) | личное использование | `python cli/skill_exchange.py install <имя>` | `/<имя>` |

## Первичная настройка (для контрибьюторов)

```bash
git clone https://github.com/Lomer275/skill-exchange_ArbitrA.git
cd skill-exchange_ArbitrA

# Установи pre-commit hook (валидация + автообновление каталога)
python cli/skill_exchange.py setup-hooks
```

## Установка скилла (для пользователей)

### Marketplace (рекомендуется)

В Claude Code:

```
/plugin marketplace add Lomer275/skill-exchange_ArbitrA
/plugin install team-skills@skill-exchange
```

После этого все скиллы команды доступны как `/team-skills:<имя>`. Обновляются автоматически.

### CLI (личная установка одного скилла)

```bash
# Посмотреть каталог
python cli/skill_exchange.py list
python cli/skill_exchange.py list --tag git    # фильтр по тегу

# Установить (по умолчанию в ~/.claude/skills/<имя>/)
python cli/skill_exchange.py install <имя>

# В путь проекта
python cli/skill_exchange.py install <имя> --project    # → ./.claude/skills/<имя>/

# В произвольный путь
python cli/skill_exchange.py install <имя> --path /custom/path

# Удалить
python cli/skill_exchange.py uninstall <имя>

# Для Claude Desktop: README в буфер
python cli/skill_exchange.py install <имя> --desktop
```

После установки **перезапусти Claude Code** чтобы скилл подхватился.

## Добавить новый скилл

```bash
# 1. Создать папку с шаблонами
python cli/skill_exchange.py new my-skill-name

# 2. Отредактировать три файла:
#    plugins/team-skills/skills/my-skill-name/SKILL.md     — промпт для Claude (с frontmatter)
#    plugins/team-skills/skills/my-skill-name/meta.json    — метаданные для каталога
#    plugins/team-skills/skills/my-skill-name/README.md    — документация

# 3. Запушить — каталог обновится автоматически (pre-commit hook)
git add plugins/team-skills/skills/my-skill-name
git commit -m "feat: add my-skill-name"
git push
```

## Формат `SKILL.md`

`SKILL.md` (uppercase!) — содержимое, которое Claude получает при активации скилла. **Обязателен YAML frontmatter** — иначе Claude Code не распознает скилл и не сможет авто-активировать его по контексту.

### Минимальная структура

```markdown
---
name: my-skill-name
description: Что делает скилл и когда его использовать. Claude читает это поле для авто-активации.
---

# My Skill

## Роль

Ты — [роль]. Твоя задача — [цель].

## Правила

- Правило 1
- Правило 2
```

### Обязательные поля frontmatter

| Поле | Требование |
|------|-----------|
| `name` | kebab-case, должен совпадать с именем папки |
| `description` | одна строка, что делает скилл и когда его использовать (Claude использует для роутинга) |

### Опциональные поля frontmatter

| Поле | Назначение |
|------|-----------|
| `allowed-tools` | пред-разрешить инструменты (`Bash(git *)`, `Read`, ...) |
| `disable-model-invocation` | `true` — отключить авто-активацию (только ручной вызов) |
| `when_to_use` | дополнительный контекст для роутинга |

Полный список — в [официальной документации](https://docs.claude.com/en/docs/claude-code/skills).

### Советы

- **Хороший `description`** = разница между «скилл активируется когда нужно» и «скилл лежит мёртвым грузом». Пиши не только *что* делает, но и *когда* использовать.
- **Будь конкретным** — чем точнее инструкции в теле, тем предсказуемее поведение Claude.
- **Указывай формат ответа** — если нужен список, таблица, код — скажи явно.
- **Добавляй примеры** — Claude лучше понимает поведение из примеров, чем из абстрактных правил.

## Формат `meta.json`

Метаданные для **каталога команды** (Claude Code их не читает — это только для нашего `README.md` и `index.json`).

```json
{
  "name": "kebab-case-name",
  "display_name": "Human Readable Name",
  "author": "твоё имя",
  "version": "1.0.0",
  "description": "Одна строка: что делает скилл",
  "tags": ["tag1", "tag2"],
  "created": "YYYY-MM-DD"
}
```

**Обязательные поля:** `name`, `author`, `description`. Поле `name` должно совпадать с именем папки.

**Теги** — свободные, но переиспользуй существующие: `git`, `code-review`, `python`, `docs`, `workflow`, `testing`.

## Валидация

Pre-commit hook автоматически проверяет на каждом коммите:

- `meta.json` валидный JSON, есть обязательные поля, `name` совпадает с именем папки
- `SKILL.md` существует, имеет валидный frontmatter, `name`/`description` присутствуют, `name` совпадает с папкой

Если что-то не так — коммит **отклоняется**, исправь и попробуй снова.

Запустить валидацию вручную:

```bash
python cli/skill_exchange.py validate
```

## Обновить локальные скиллы

Через marketplace (если установил через `/plugin install`):

```
/plugin update team-skills@skill-exchange
```

Через CLI:

```bash
python cli/skill_exchange.py update
```

`update` делает `git pull` и переустанавливает все скиллы из `installed[]` в `default_path`.

## Как работает pre-commit hook

При каждом `git commit` хук автоматически:

1. **Валидирует** все скиллы (см. выше). Если есть ошибки — коммит отклоняется.
2. Сканирует все папки в `plugins/team-skills/skills/`.
3. Читает `meta.json` каждого скилла.
4. Перегенерирует `plugins/team-skills/skills/index.json`.
5. Перегенерирует корневой `README.md` с таблицей каталога.
6. Добавляет оба файла в коммит.

Тебе ничего делать не нужно — каталог всегда актуален.

## Устранение проблем

**Hook не запускается при коммите**

```bash
python cli/skill_exchange.py setup-hooks
ls .git/hooks/pre-commit
```

На Windows убедись что Python в PATH: `python --version`.

---

**`python` не найдена**

Используй `python3`:

```bash
python3 cli/skill_exchange.py list
```

---

**Marketplace добавлен, но плагин не активируется**

1. Проверь, что плагин включён: `/plugin list`
2. Ручной запуск: `/plugin update team-skills@skill-exchange`
3. Перезапусти Claude Code (не просто новый чат — полностью перезапусти CLI/IDE)

---

**Скилл установлен через CLI, но не появляется в Claude Code**

1. Проверь путь: `python cli/skill_exchange.py config`. По умолчанию `~/.claude/skills/`.
2. Папка с `SKILL.md` действительно создалась? `ls ~/.claude/skills/<имя>/SKILL.md`
3. Полностью перезапусти Claude Code.
4. Проверь, что у `SKILL.md` есть frontmatter (`---` сверху).

---

**`git push` не работает**

Запроси доступ к репо у владельца — нужны collaborator-права.
