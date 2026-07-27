# CRM Methods Reference

## Deal Fields (crm.deal.fields)

### System fields (select[]=*)
| Field | Type | Description |
|-------|------|-------------|
| ID | int | Deal ID |
| TITLE | string | Deal title |
| STAGE_ID | string | Stage code e.g. C4:1, C4:NEW |
| CATEGORY_ID | int | Funnel ID (4=БФЛ) |
| ASSIGNED_BY_ID | int | Responsible user ID |
| CONTACT_ID | int | Primary contact ID |
| COMPANY_ID | int | Company ID |
| OPPORTUNITY | float | Deal amount |
| CURRENCY_ID | string | Currency |
| DATE_CREATE | datetime | Created date |
| DATE_MODIFY | datetime | Modified date |
| CLOSEDATE | date | Close date |
| BEGINDATE | date | Start date |
| COMMENTS | text | Comments/notes |
| SOURCE_ID | string | Source code |
| SOURCE_DESCRIPTION | text | Source description |
| LEAD_ID | int | Source lead ID |
| OPENED | Y/N | Available to all |
| CLOSED | Y/N | Closed flag |
| UF_CRM_* | mixed | Custom fields |

### Stage IDs format for БФЛ (CATEGORY_ID=4)
- `C4:NEW` — new
- `C4:PREPARATION` — in progress (depends on config)
- `C4:WON` — successfully closed
- `C4:LOSE` — lost
- Custom stages: `C4:{STAGE_SORT_NUMBER}`

Get all stages:
```
METHOD: crm.deal.stage.list
PARAMS: {"select_extras": {"CATEGORY_ID": 4}}
```
Or:
```
METHOD: crm.status.list
PARAMS: {"filter": {"ENTITY_ID": "DEAL_STAGE_4"}}
```

---

## crm.deal.list

**Full signature:**
```json
{
  "order": {"DATE_MODIFY": "DESC"},
  "filter": {
    "CATEGORY_ID": 4,
    ">DATE_MODIFY": "2024-01-01T00:00:00",
    "STAGE_ID": "C4:1",
    "ASSIGNED_BY_ID": 45,
    "!=CLOSED": "Y"
  },
  "select": ["ID", "TITLE", "STAGE_ID", "ASSIGNED_BY_ID", "UF_CRM_*"],
  "start": 0
}
```
Response: `{"result": [...], "total": 123, "next": 50}`

---

## crm.deal.update

```json
{
  "id": 456,
  "fields": {
    "STAGE_ID": "C4:3",
    "ASSIGNED_BY_ID": 45,
    "UF_CRM_1234567890": "значение"
  }
}
```

---

## crm.contact.list / get

```json
{
  "filter": {"ID": 123},
  "select": ["ID", "NAME", "LAST_NAME", "PHONE", "EMAIL", "ASSIGNED_BY_ID", "UF_CRM_*"]
}
```

Phone/Email are arrays:
```json
"PHONE": [{"VALUE": "+79001234567", "VALUE_TYPE": "WORK"}]
```

---

## crm.lead.list / update

Lead stages via:
```
METHOD: crm.status.list
PARAMS: {"filter": {"ENTITY_ID": "STATUS"}}
```

---

## crm.item.list (Smart Processes)

```json
{
  "entityTypeId": 1094,
  "order": {"id": "DESC"},
  "filter": {
    "stageId": "DT1094_1:1",
    "assignedById": 45
  },
  "select": ["*", "ufCrm_*"],
  "start": 0
}
```

## crm.item.get

```json
{
  "entityTypeId": 1094,
  "id": 123
}
```

## crm.item.update

```json
{
  "entityTypeId": 1094,
  "id": 123,
  "fields": {
    "stageId": "DT1094_1:2",
    "assignedById": 45,
    "ufCrm_1_1234567890": "value"
  }
}
```

## crm.item.add

```json
{
  "entityTypeId": 1094,
  "fields": {
    "title": "Новый элемент",
    "stageId": "DT1094_1:1",
    "assignedById": 45,
    "contactId": 123
  }
}
```

---

## Getting Custom Field IDs

```
METHOD: crm.deal.fields
PARAMS: {}
```
Returns all fields including `UF_CRM_*` with type info.

For smart processes:
```
METHOD: crm.item.fields
PARAMS: {"entityTypeId": 1094}
```

---

## Relation: Deal ↔ Contact (multiple contacts)

```
# Get all contacts for deal
METHOD: crm.deal.contact.items.get
PARAMS: {"id": 456}

# Set contacts for deal
METHOD: crm.deal.contact.items.set
PARAMS: {
  "id": 456,
  "items": [
    {"CONTACT_ID": 123, "SORT": 10, "IS_PRIMARY": "Y"},
    {"CONTACT_ID": 124, "SORT": 20, "IS_PRIMARY": "N"}
  ]
}
```

---

## Timeline (Activities in CRM)

```
# Add comment to deal
METHOD: crm.timeline.comment.add
PARAMS: {
  "fields": {
    "ENTITY_TYPE": "deal",
    "ENTITY_ID": 456,
    "COMMENT": "Текст комментария"
  }
}

# Add log entry
METHOD: crm.timeline.logmessage.add  
PARAMS: {
  "fields": {
    "ENTITY_TYPE": "deal",
    "ENTITY_ID": 456,
    "TEXT": "Лог запись",
    "TITLE": "Заголовок"
  }
}
```

---

## Source / Channel tracking

Source IDs (crm.status.list ENTITY_ID=SOURCE):
- `CALL` — phone call
- `EMAIL` — email
- `WEB` — website
- `SELF` — personal contacts
- Custom sources have custom IDs
