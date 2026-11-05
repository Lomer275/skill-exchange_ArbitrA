# Bitrix24 Environment — пример

Этот справочник описывает имена переменных и несекретные настройки проекта.
Не записывайте токены и URL вебхуков в Markdown, файлы навыка или чат.

## Переменные окружения

- `BITRIX_WEBHOOK` — поступает из хранилища секретов проекта: менеджера паролей
  или игнорируемого git env-файла, заполненного в редакторе, без команд shell со значением.
- Домен портала и несекретные ID воронок и типов уточняются чтением API проекта.

## Воронки (CATEGORY_ID)

Узнай через `crm.category.list`:

```
| Funnel name        | CATEGORY_ID |
|--------------------|-------------|
| <Main pipeline>    | <ID>        |
| <Other pipeline>   | <ID>        |
```

## Smart Processes (entityTypeId)

Узнай через `crm.type.list`:

```
| Smart Process      | entityTypeId | Stage prefix      |
|--------------------|--------------|-------------------|
| <Process A>        | <typeId>     | DT<typeId>_<cat>: |
```

## Custom Fields (UF_CRM_*)

Узнай через `crm.deal.userfield.list` (для сделок) или `crm.item.fields` с `entityTypeId` (для смарт-процессов).

## n8n bridge (если используешь)

```
n8n base URL:   https://n8n.example.com
Bridge workflow ID: <N8N_BRIDGE_WORKFLOW_ID>
```
