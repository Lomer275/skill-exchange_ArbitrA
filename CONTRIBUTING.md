# Contributing to Skill Exchange ArbitrA

Гайд для команды по добавлению и обновлению Claude Code скиллов.

## Требования

- Python 3.8+
- Git
- Клонированный репозиторий

## Первичная настройка (один раз)

```bash
# 1. Клонируй репо
git clone <url> skill-exchange_ArbitrA
cd skill-exchange_ArbitrA

# 2. Установи pre-commit hook (обновляет каталог при каждом коммите)
python cli/skill_exchange.py setup-hooks

# 3. Укажи куда устанавливать скиллы локально
python cli/skill_exchange.py config --set-path /путь/к/твоим/плагинам
# Например:
#   Windows: python cli/skill_exchange.py config --set-path C:\Users\me\.claude\plugins
#   Mac/Linux: python cli/skill_exchange.py config --set-path ~/.claude/plugins
```

## Установить скилл из библиотеки

```bash
# Посмотреть все скиллы
python cli/skill_exchange.py list

# Установить конкретный скилл
python cli/skill_exchange.py install <skill-name>

# Установить в конкретную папку
python cli/skill_exchange.py install <skill-name> --path /custom/path

# Для Claude Desktop: скопировать README в буфер обмена
python cli/skill_exchange.py install <skill-name> --desktop
```

После установки перезапусти Claude Code.

## Добавить новый скилл

```bash
# 1. Создать папку скилла с шаблонами
python cli/skill_exchange.py new my-skill-name

# 2. Отредактируй три файла:
#    skills/my-skill-name/skill.md    — содержимое скилла для Claude
#    skills/my-skill-name/meta.json   — метаданные (имя, теги, описание)
#    skills/my-skill-name/README.md   — документация для команды

# 3. Запушь — каталог обновится автоматически
git add skills/my-skill-name
git commit -m "feat: add my-skill-name"
git push
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

Обязательные поля: `name`, `author`, `description`.

## Обновить локальные скиллы

```bash
python cli/skill_exchange.py update
```

Выполняет `git pull` и переустанавливает все ранее установленные скиллы.

## Как работает pre-commit hook

При каждом `git commit` хук автоматически:
1. Сканирует все папки в `skills/`
2. Читает `meta.json` каждого скилла
3. Перегенерирует `skills/index.json`
4. Перегенерирует `README.md` с таблицей каталога
5. Добавляет оба файла в коммит

Тебе ничего делать не нужно — каталог всегда актуален.
