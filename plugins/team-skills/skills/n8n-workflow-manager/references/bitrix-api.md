# Bitrix24 API Reference — Экспресс-Банкрот

## Базовые параметры

- **Portal**: `<YOUR_BITRIX_PORTAL>`
- **Webhook endpoint**: `https://<YOUR_BITRIX_PORTAL>/rest/<USER_ID>/<WEBHOOK_TOKEN>/`
- **Формат вызова из n8n**: POST на `{endpoint}{METHOD}`

## Сделки (CRM Deals)

| Метод | Описание |
|-------|----------|
| `crm.deal.list` | Список сделок с фильтром |
| `crm.deal.get` | Сделка по ID |
| `crm.deal.update` | Обновить поля сделки |
| `crm.deal.add` | Создать сделку |

Основной воронка: `CATEGORY_ID = <MAIN_FUNNEL_ID>` (пример: 4) (Main pipeline (example)).  
Другие: Pipeline B, C, D, E (example names).

## Лиды (CRM Leads)

| Метод | Описание |
|-------|----------|
| `crm.lead.list` | Список лидов |
| `crm.lead.get` | Лид по ID |
| `crm.lead.update` | Обновить лид |

## Контакты и компании

| Метод | Описание |
|-------|----------|
| `crm.contact.list` | Список контактов |
| `crm.contact.update` | Обновить контакт |
| `crm.company.list` | Список компаний |
| `crm.company.update` | Обновить компанию |

## Smart Processes (Умные процессы)

| entityTypeId | Название |
|-------------|----------|
| 1094 | Smart-process A (example) |
| 1122 | Smart-process B (example) |
| 1104 | Smart-process C (example) |
| 1112 | Логи встреч/договоров |

Методы:
- `crm.item.list` — с параметром `entityTypeId`
- `crm.item.get`
- `crm.item.update`
- `crm.item.add`

## Batch API

```
POST /rest/<USER_ID>/<WEBHOOK_TOKEN>/batch
{
  "halt": 0,
  "cmd": {
    "deals": "crm.deal.list?filter[CATEGORY_ID]=4&select[]=ID&select[]=TITLE",
    "contacts": "crm.contact.list?filter[...]=...&select[]=ID"
  }
}
```

До 50 команд в одном запросе.

## Пользователи и права

| Метод | Описание |
|-------|----------|
| `user.get` | Получить пользователя |
| `user.update` | Обновить пользователя |
| `im.user.list` | Список пользователей чата |
| `bizproc.workflow.instances` | Список запущенных БП |

## Бизнес-процессы

| Метод | Описание |
|-------|----------|
| `bizproc.workflow.start` | Запустить БП |
| `bizproc.workflow.terminate` | Остановить БП |
| `bizproc.workflow.template.list` | Список шаблонов |
| `bizproc.task.list` | Задачи БП |

⚠️ `bizproc.workflow.template.update` — только через OAuth app, не через webhook токен.

## Диск (Bitrix Drive)

- Задержки: 500ms между чтением папок, 3s между записью
- `disk.folder.getchildren` — содержимое папки
- `disk.file.uploadurl` — загрузка файла

## Фильтры и пагинация

```json
{
  "filter": { "CATEGORY_ID": 4, ">DATE_CREATE": "2024-01-01" },
  "select": ["ID", "TITLE", "ASSIGNED_BY_ID", "STAGE_ID"],
  "order": { "DATE_CREATE": "DESC" },
  "start": 0
}
```

Для получения всех записей: итерировать по `start` с шагом 50.
