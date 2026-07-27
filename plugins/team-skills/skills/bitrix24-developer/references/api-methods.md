# Bitrix24 REST API — Method Reference

## CRM — Deals (crm.deal.*)

### crm.deal.list
```json
{
  "filter": {
    "CATEGORY_ID": 4,
    "STAGE_ID": "C4:1",
    "@ASSIGNED_BY_ID": [12, 15],
    ">DATE_CREATE": "2024-01-01T00:00:00+03:00"
  },
  "select": ["ID", "TITLE", "STAGE_ID", "ASSIGNED_BY_ID", "UF_CRM_123456"],
  "order": {"DATE_MODIFY": "DESC"},
  "start": 0
}
```
Response: `{ result: [...], next: 50, total: 123 }`

### crm.deal.get
```json
{ "id": 456 }
```

### crm.deal.add
```json
{
  "fields": {
    "TITLE": "Новая сделка",
    "CATEGORY_ID": 4,
    "STAGE_ID": "C4:1",
    "ASSIGNED_BY_ID": 15,
    "CONTACT_ID": 789,
    "OPPORTUNITY": 150000,
    "CURRENCY_ID": "RUB",
    "UF_CRM_123456": "value"
  }
}
```
Response: `{ result: 456 }` (new deal ID)

### crm.deal.update
```json
{
  "id": 456,
  "fields": {
    "STAGE_ID": "C4:2",
    "ASSIGNED_BY_ID": 20
  }
}
```

### crm.deal.fields
No params. Returns all field definitions with types, labels, isRequired, isReadOnly.

### crm.deal.userfield.list
```json
{ "filter": {"ENTITY_ID": "CRM_DEAL"} }
```
Returns custom UF_CRM_* field definitions.

---

## CRM — Leads (crm.lead.*)

### crm.lead.list
Same pattern as crm.deal.list. No CATEGORY_ID filter needed.
Stage filter: `STAGE_ID: "NEW"` / `"IN_PROCESS"` / `"WON"` / `"JUNK"`

### crm.lead.add
```json
{
  "fields": {
    "TITLE": "Новый лид",
    "NAME": "Иван",
    "LAST_NAME": "Петров",
    "PHONE": [{"VALUE": "+79001234567", "VALUE_TYPE": "WORK"}],
    "EMAIL": [{"VALUE": "test@mail.ru", "VALUE_TYPE": "WORK"}],
    "ASSIGNED_BY_ID": 15,
    "SOURCE_ID": "CALL"
  }
}
```

---

## CRM — Contacts (crm.contact.*)

### crm.contact.list / get / update / add
Same pattern. Key fields:
- `NAME`, `LAST_NAME`, `SECOND_NAME`
- `PHONE` — array: `[{"VALUE": "+7...", "VALUE_TYPE": "WORK"}]`
- `EMAIL` — array: `[{"VALUE": "...", "VALUE_TYPE": "WORK"}]`
- `ASSIGNED_BY_ID`
- `UF_CRM_*`

### crm.contact.company.add (link contact to company)
```json
{ "id": 123, "fields": {"COMPANY_ID": 456} }
```

---

## CRM — Smart Processes (crm.item.*)

### crm.item.list
```json
{
  "entityTypeId": 1094,
  "filter": {
    "stageId": "DT1094_4:NEW",
    "assignedById": 15
  },
  "select": ["id", "title", "assignedById", "stageId", "createdTime", "ufCrm40_*"],
  "order": {"createdTime": "DESC"},
  "start": 0
}
```
Note: field names in camelCase for smart processes (not UPPER_CASE like deals)

### crm.item.add
```json
{
  "entityTypeId": 1094,
  "fields": {
    "title": "Новый элемент",
    "assignedById": 15,
    "stageId": "DT1094_4:NEW",
    "ufCrm40_123456": "value"
  }
}
```

### crm.item.fields
```json
{ "entityTypeId": 1094 }
```
Returns field definitions for that smart process.

### crm.type.list
No params. Returns all smart process type definitions with entityTypeId, name, etc.

### Stage ID format for smart processes
`DT{entityTypeId}_{categoryId}:{stageCode}`
Example: `DT1094_4:NEW`, `DT1094_4:SUCCESS`, `DT1094_4:FAIL`

---

## CRM — Funnels & Stages

### crm.category.list
```json
{ "entityTypeId": 2 }
```
entityTypeId: 2 = deals, 1 = leads, 3 = contacts, 4 = companies

### crm.status.list (deal stages)
```json
{
  "filter": {"ENTITY_ID": "DEAL_STAGE_C4"}
}
```
Returns: `{ STATUS_ID, NAME, SORT, ... }`
ENTITY_ID format: `DEAL_STAGE_C{CATEGORY_ID}`

---

## Users

### user.get
```json
{ "ID": 15 }
```
Or: `{ "filter": {"ACTIVE": true, "UF_DEPARTMENT": [5]} }`

### user.search
```json
{ "NAME": "Иван", "LAST_NAME": "Петров" }
```

### user.update
```json
{
  "ID": 15,
  "FIELDS": {
    "UF_DEPARTMENT": [5, 8]
  }
}
```

### user.fields
No params. Returns all user field definitions.

---

## Tasks

### tasks.task.list
```json
{
  "filter": {
    "RESPONSIBLE_ID": 15,
    "STATUS": 2,
    ">=DEADLINE": "2024-01-01"
  },
  "select": ["ID", "TITLE", "STATUS", "RESPONSIBLE_ID", "DEADLINE", "UF_*"],
  "params": {"ORDER": {"DEADLINE": "ASC"}, "START": 0}
}
```
Status values: 1=new, 2=pending, 3=in_progress, 4=supposedly_completed, 5=completed, 6=deferred, 7=declined

### tasks.task.add
```json
{
  "fields": {
    "TITLE": "Задача",
    "RESPONSIBLE_ID": 15,
    "CREATED_BY": 1,
    "DESCRIPTION": "Описание",
    "DEADLINE": "2024-12-31T23:59:59+03:00",
    "UF_CRM_TASK": ["CRM_DEAL_456"]
  }
}
```

### tasks.task.update
```json
{
  "taskId": 123,
  "fields": { "STATUS": 5 }
}
```

---

## Disk

### disk.storage.getstoragelist
No params. Returns all available storages.

### disk.folder.getchildren
```json
{
  "id": 123,
  "filter": {"NAME": "%договор%"},
  "start": 0
}
```

### disk.folder.add
```json
{
  "id": 123,
  "data": {"NAME": "Новая папка"}
}
```

### disk.file.upload
Requires multipart/form-data. Fields: `id` (folder ID), `data[NAME]`, `file` (binary).

### disk.file.get
```json
{ "id": 456 }
```

---

## Business Processes

### bizproc.workflow.template.list
```json
{
  "filter": {"DOCUMENT_TYPE": ["crm", "CCrmDocumentDeal", "DEAL"]}
}
```
Returns: ID, NAME, DOCUMENT_TYPE, ACTIVE, etc.

### bizproc.workflow.start
```json
{
  "TEMPLATE_ID": 123,
  "DOCUMENT_ID": ["crm", "CCrmDocumentDeal", 456],
  "PARAMETERS": {
    "TargetUser": "user_15"
  }
}
```

### bizproc.workflow.instances.list
```json
{
  "filter": {
    "DOCUMENT_ID": "456",
    "DOCUMENT_TYPE": "CCrmDocumentDeal"
  }
}
```

### bizproc.workflow.terminate
```json
{ "ID": "workflow-instance-id" }
```

### bizproc.task.list (pending BP tasks)
```json
{
  "filter": {"USER_ID": 15, "STATUS": 0}
}
```

### bizproc.task.complete
```json
{
  "TASK_ID": 123,
  "USER_ID": 15,
  "STATUS": "yes",
  "COMMENT": "Подтверждено"
}
```

---

## Activities & Timeline

### crm.activity.list
```json
{
  "filter": {
    "OWNER_TYPE_ID": 2,
    "OWNER_ID": 456,
    "TYPE_ID": 2
  }
}
```
OWNER_TYPE_ID: 1=lead, 2=deal, 3=contact, 4=company
TYPE_ID: 1=email, 2=call, 3=task

### crm.timeline.comment.add
```json
{
  "fields": {
    "ENTITY_ID": 456,
    "ENTITY_TYPE": "deal",
    "COMMENT": "Текст комментария"
  }
}
```

---

## Webhooks & Events

### event.bind (not available via webhook token — requires OAuth app)

### Outgoing webhooks (triggered by Bitrix24 events)
Configure in Bitrix24 admin: Marketplace → Webhooks → Outgoing webhooks
Available events: ONCRMDEALADD, ONCRMDEALEDIT, ONCRMDEALDELETE, ONCRMLEAD*, etc.

---

## Batch API — Advanced Patterns

### Sequential with references (result of one call as input to another)
```json
{
  "halt": 1,
  "cmd": {
    "getDeal": "crm.deal.get?id=101",
    "getContact": "crm.contact.get?id=$result[getDeal][CONTACT_ID]"
  }
}
```
Use `$result[commandKey][fieldName]` to reference previous results.

### Mass update pattern
```javascript
// Build batch of up to 50 updates
const cmd = {};
items.slice(0, 50).forEach((item, i) => {
  cmd[`upd${i}`] = `crm.deal.update?id=${item.id}&fields[STAGE_ID]=C4:WON`;
});

const response = await this.helpers.httpRequest({
  method: 'POST',
  url: 'https://bitrix.express-bankrot.ru/rest/30351/rzoev7lscjxgq9i6/batch',
  body: { halt: 0, cmd }
});
// response.result.result — object with each command's result
// response.result.result_error — object with each command's error (if any)
```
