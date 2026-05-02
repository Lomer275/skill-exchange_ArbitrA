---
name: bitrix24-developer
description: "'Expert Bitrix24 REST API developer assistant. Use this skill whenever the user asks about Bitrix24: CRM (deals, leads, contacts, companies), smart processes, business processes (BP), disk, tasks, users, automation, batch API calls, or any REST API method. Also trigger for questions about Bitrix24 structure, field names, entity types, funnel configuration, workflow templates, webhook setup, or integration patterns. Always use when user mentions 'битрикс', 'bitrix', 'CRM', 'смарт-процесс', 'бизнес-процесс', 'воронка', 'сделки', 'лиды', 'Битрикс24'.'"
---
# Bitrix24 Developer Skill

> **Important:** этот скилл — generic-набор паттернов работы с Bitrix24 REST API. Конкретные ID воронок, entityTypeId смарт-процессов, custom-поля, webhook-токены и URL портала **специфичны для каждого проекта**. Скопируй [references/env.example.md](references/env.example.md) в свой репо и заполни своими значениями.

## Environment Constants (заполняется в твоём проекте)

```
Portal:       <YOUR_BITRIX_PORTAL>            # пример: bitrix.example.com
Webhook base: https://<YOUR_BITRIX_PORTAL>/rest/<USER_ID>/<WEBHOOK_TOKEN>/
n8n bridge:   Workflow ID = <N8N_BRIDGE_WORKFLOW_ID>  (если используется n8n MCP-мост)
```

### Funnel IDs (CATEGORY_ID) — узнать своими

Узнавай через `crm.category.list` — у каждого портала свои воронки. Записывай маппинг в свой проектный `BITRIX_ENV.md`.

### Smart Process Entity Type IDs — узнать своими

Узнавай через `crm.type.list` — entityTypeId назначаются динамически при создании смарт-процесса.

---

## How to Call the API (via n8n MCP bridge)

```
METHOD: crm.deal.list
PARAMS: {
  "filter": {"CATEGORY_ID": 4, "STAGE_ID": "C4:1"},
  "select": ["ID", "TITLE", "ASSIGNED_BY_ID", "UF_CRM_*"],
  "start": 0
}
```

**Direct REST call format:**
```
GET/POST https://<YOUR_BITRIX_PORTAL>/rest/<USER_ID>/<WEBHOOK_TOKEN>/METHOD
```

---

## Core API Methods Reference

> For detailed method signatures, see references/api-methods.md
> For CRM field structures, see references/crm-fields.md
> For smart process patterns, see references/smart-processes.md
> For business process patterns, see references/business-processes.md
> For known pitfalls, see references/pitfalls.md

### Quick Method Index

**CRM - Deals**
- `crm.deal.list` / `crm.deal.get` / `crm.deal.add` / `crm.deal.update` / `crm.deal.delete`
- `crm.deal.fields` — get all field definitions
- `crm.deal.userfield.list` — custom fields (UF_CRM_*)

**CRM - Leads**
- `crm.lead.list` / `crm.lead.get` / `crm.lead.add` / `crm.lead.update`

**CRM - Contacts & Companies**
- `crm.contact.list` / `crm.contact.get` / `crm.contact.update`
- `crm.company.list` / `crm.company.get` / `crm.company.update`

**CRM - Smart Processes**
- `crm.item.list` / `crm.item.get` / `crm.item.add` / `crm.item.update`
- `crm.item.fields` — pass entityTypeId
- `crm.type.list` — list all smart process types

**CRM - Stages / Funnels**
- `crm.status.list` — deal stages (filter by ENTITY_ID: "DEAL_STAGE_C4" for funnel 4)
- `crm.category.list` / `crm.category.get`

**Users**
- `user.get` / `user.search` / `user.update`

**Tasks**
- `tasks.task.list` / `tasks.task.get` / `tasks.task.add` / `tasks.task.update`

**Disk**
- `disk.folder.getchildren` / `disk.file.get` / `disk.file.upload`
- `disk.folder.add` / `disk.storage.getstoragelist`

**Business Processes**
- `bizproc.workflow.start` / `bizproc.workflow.terminate`
- `bizproc.workflow.template.list`
- `bizproc.task.list` / `bizproc.task.complete`

**Batch API**
- `batch` — up to 50 operations per request

---

## Batch API Pattern

```json
METHOD: batch
PARAMS: {
  "halt": 0,
  "cmd": {
    "deal1": "crm.deal.get?id=101",
    "deal2": "crm.deal.get?id=102",
    "contact1": "crm.contact.get?id=201"
  }
}
```

- `halt: 0` — продолжить даже при ошибке в одном запросе
- `halt: 1` — остановить при первой ошибке
- Ответ: `result.result.{key}` для каждого запроса
- Макс. 50 операций на один batch

---

## Pagination Pattern

Bitrix24 возвращает максимум 50 записей. Для получения всех:

```javascript
let allItems = [];
let start = 0;

do {
  const response = await this.helpers.httpRequest({
    method: 'POST',
    url: 'https://<YOUR_BITRIX_PORTAL>/rest/<USER_ID>/<WEBHOOK_TOKEN>/crm.deal.list',
    body: { filter: { CATEGORY_ID: 4 }, select: ['ID', 'TITLE'], start }
  });
  allItems = allItems.concat(response.result || []);
  start = response.next ?? null;
} while (start !== null);
```

`response.next` — следующий offset. Если нет — все записи получены.

---

## CRM Filter Operators

| Operator | Meaning |
|----------|---------|
| `FIELD` | equals |
| `!FIELD` | not equals |
| `>FIELD` | greater than |
| `<FIELD` | less than |
| `%FIELD` | LIKE (contains) |
| `@FIELD` | IN (array) |
| `!@FIELD` | NOT IN |

Example: `{ "filter": { "@ASSIGNED_BY_ID": [12, 15], ">DATE_CREATE": "2024-01-01" } }`

---

## Smart Processes — Key Patterns

```javascript
// List items
METHOD: crm.item.list
PARAMS: {
  "entityTypeId": 1094,
  "filter": { "stageId": "DT1094_4:NEW" },
  "select": ["id", "title", "assignedById", "stageId", "ufCrm*"]
}

// Stage ID format: DT{entityTypeId}_{categoryId}:{stageCode}
```

---

## Business Processes — CRITICAL Constraints

CRITICAL LIMITATION:
- `bizproc.workflow.template.add/update` требуют OAuth-контекст приложения
- Webhook-токены возвращают ACCESS_DENIED
- Шаблоны, импортированные через UI, НЕЛЬЗЯ обновить через API
- Только шаблоны, созданные через API тем же приложением, можно обновить через API

```javascript
// Document ID formats for bizproc.workflow.start:
// Deal:    ["crm", "CCrmDocumentDeal", {ID}]
// Lead:    ["crm", "CCrmDocumentLead", {ID}]
// Contact: ["crm", "CCrmDocumentContact", {ID}]
// Smart:   ["crm", "Bitrix\\Crm\\Integration\\BizProc\\Document\\Dynamic", {ID}]
```

---

## n8n + Bitrix Key Patterns

### SplitInBatches vs Code loops
ВСЕГДА используй SplitInBatches для обработки >100 записей.
Code node loops вызывают timeout (300 сек лимит task runner).

### DNS issues in Docker
При `EAI_AGAIN` ошибках:
- Добавь dns: [8.8.8.8, 1.1.1.1] в docker-compose.yml
- Используй extra_hosts для статического маппинга bitrix домена
- Включи Retry on Fail (5 retries, 3000ms) на HTTP nodes

### Rate Limiting
- Disk API: 500ms между чтениями папок, 3s между записями
- CRM batch: 200-500ms между пакетами при массовых обновлениях
- Webhook: ~2 запроса/сек

### Code node HTTP
```javascript
const response = await this.helpers.httpRequest({
  method: 'POST',
  url: 'https://<YOUR_BITRIX_PORTAL>/rest/<USER_ID>/<WEBHOOK_TOKEN>/METHOD',
  body: { ...params }
});
```

---

## Deal Stage ID Format

`C{CATEGORY_ID}:{STAGE_CODE}`
- `C4:1` — первая стадия воронки Main pipeline (example)
- `C4:WON` — успешно завершена
- `C4:LOSE` — провалена

---

## Common Field Names (Deal)

| Field | Description |
|-------|-------------|
| `ID` | Deal ID |
| `TITLE` | Title |
| `STAGE_ID` | Stage |
| `CATEGORY_ID` | Funnel ID |
| `ASSIGNED_BY_ID` | Responsible user ID |
| `CONTACT_ID` | Primary contact |
| `COMPANY_ID` | Company |
| `DATE_CREATE` | Creation date |
| `DATE_MODIFY` | Last modified |
| `OPPORTUNITY` | Amount |
| `CURRENCY_ID` | Currency |
| `UF_CRM_*` | Custom fields |
