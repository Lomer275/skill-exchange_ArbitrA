# Contributing to Skill Exchange ArbitrA

Гайд для команды по добавлению и обновлению Claude Code скиллов.

## Требования

- Python 3.8+ (`python --version` чтобы проверить)
- Git
- Claude Code (CLI или расширение VSCode/JetBrains)

## Первичная настройка (один раз)

```bash
# 1. Клонируй репо
git clone https://github.com/Lomer275/skill-exchange_ArbitrA.git
cd skill-exchange_ArbitrA

# 2. Установи pre-commit hook (обновляет каталог при каждом коммите)
python cli/skill_exchange.py setup-hooks

# 3. Укажи куда устанавливать скиллы локально
python cli/skill_exchange.py config --set-path <путь>
```

### Где найти путь к плагинам Claude Code

Зависит от того, как ты используешь Claude Code:

| Сценарий | Путь |
|---|---|
| **Глобально** (Windows) | `C:\Users\<имя>\.claude\plugins` |
| **Глобально** (Mac/Linux) | `~/.claude/plugins` |
| **Только для проекта** | `.claude/plugins` внутри папки проекта |

Если папка `.claude/plugins` не существует — CLI создаст её автоматически.

> Не уверен где? Открой Claude Code, введи `/plugins` или посмотри в `~/.claude/` — там должна быть папка `plugins`.

## Установить скилл из библиотеки

```bash
# Посмотреть все скиллы
python cli/skill_exchange.py list

# Фильтр по тегу
python cli/skill_exchange.py list --tag git

# Установить скилл (в путь из конфига)
python cli/skill_exchange.py install <skill-name>

# Установить глобально (все проекты)
python cli/skill_exchange.py install <skill-name> --global

# Установить только для текущего проекта
python cli/skill_exchange.py install <skill-name> --project

# Установить в конкретную папку
python cli/skill_exchange.py install <skill-name> --path /custom/path

# Для Claude Desktop: скопировать README в буфер обмена
python cli/skill_exchange.py install <skill-name> --desktop
```

После установки **перезапусти Claude Code** чтобы скилл стал доступен.

## Добавить новый скилл

```bash
# 1. Создать папку скилла с шаблонами
python cli/skill_exchange.py new my-skill-name

# 2. Отредактируй три файла (см. описание ниже):
#    skills/my-skill-name/skill.md    — инструкции для Claude
#    skills/my-skill-name/meta.json   — метаданные (имя, теги, описание)
#    skills/my-skill-name/README.md   — документация для команды

# 3. Запушь — каталог обновится автоматически
git add skills/my-skill-name
git commit -m "feat: add my-skill-name"
git push
```

## Что писать в `skill.md`

`skill.md` — это инструкции, которые Claude получает при активации скилла. Пиши его как системный промпт: что должен делать Claude, в какой роли, какие правила соблюдать.

### Структура `skill.md`

```markdown
# Название скилла

Краткое описание: что делает этот скилл и когда его использовать.

## Роль

Ты — [описание роли]. Твоя задача — [цель].

## Правила

- Правило 1
- Правило 2

## Как работать

1. Шаг 1
2. Шаг 2

## Пример

[Пример использования или диалога]
```

### Советы

- **Будь конкретным** — чем точнее инструкция, тем предсказуемее поведение Claude
- **Указывай формат ответа** — если нужен список, таблица, код — скажи об этом явно
- **Добавляй примеры** — Claude лучше понимает поведение из примеров, чем из абстрактных правил
- **Короче лучше** — 200-500 строк достаточно для большинства скиллов

### Пример хорошего `skill.md`

```markdown
# Code Reviewer

Ты проводишь code review. Анализируй код который тебе показывают и давай конкретные замечания.

## Правила

- Сначала краткое резюме (1-2 предложения): что делает код и насколько он хорош
- Затем список замечаний по категориям: Критические / Важные / Незначительные
- Каждое замечание: что не так, почему это проблема, как исправить (с примером кода)
- Не придирайся к стилю если он уже соответствует проекту

## Формат ответа

**Резюме:** ...

**Критические:**
- [ ] Описание → Почему → Как исправить

**Важные:**
- [ ] ...
```

## Формат `meta.json`

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

**Обязательные поля:** `name`, `author`, `description`.

**Теги** — свободные, но старайся переиспользовать существующие: `git`, `code-review`, `python`, `docs`, `workflow`, `testing` и т.д.

## Обновить локальные скиллы

```bash
python cli/skill_exchange.py update
```

Выполняет `git pull` и переустанавливает все ранее установленные скиллы в `default_path`.

## Как работает pre-commit hook

При каждом `git commit` хук автоматически:
1. Сканирует все папки в `skills/`
2. Читает `meta.json` каждого скилла
3. Перегенерирует `skills/index.json`
4. Перегенерирует `README.md` с таблицей каталога
5. Добавляет оба файла в коммит

Тебе ничего делать не нужно — каталог всегда актуален.

## Устранение проблем

**Hook не запускается при коммите**

```bash
# Переустанови hook
python cli/skill_exchange.py setup-hooks

# Проверь что он там есть
ls .git/hooks/pre-commit
```

На Windows убедись что Python есть в PATH: `python --version`

---

**`python` не найдена команда**

На некоторых системах нужно использовать `python3`:
```bash
python3 cli/skill_exchange.py list
```

---

**Скилл установлен, но не появляется в Claude Code**

1. Убедись что путь установки правильный: `python cli/skill_exchange.py config`
2. Полностью перезапусти Claude Code (не просто новый чат)
3. Проверь что папка скилла скопировалась: открой путь из конфига и посмотри там

---

**`git push` не работает**

Убедись что у тебя есть доступ к репо на GitHub. Попроси владельца добавить тебя как collaborator.
