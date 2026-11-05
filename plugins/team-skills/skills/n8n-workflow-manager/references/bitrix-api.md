# Bitrix24 API Reference — Express-Bankrot

## Writes to Bitrix

1. Reads (`*.get`, `*.list`, `*.fields`, and batches containing only reads) are unrestricted.
2. Every write, including `crm.*.add/update/delete`, batches containing writes,
   `bizproc.workflow.start/terminate/kill`, `bizproc.task.complete`,
   `tasks.task.add/update`, `task.commentitem.add`, `disk.*.upload/delete/rename`,
   `user.update`, `event.bind/unbind`, and `placement.bind`, must first use the
   project's sandbox if one exists. Production writes must use the write route
   declared by the project (for example, its integration pipeline), or wait for
   the human's explicit “yes” in this conversation to a concrete list of methods,
   entity IDs, and fields with “before → after” values.
3. Bulk operations (any batch or a loop over more than one entity) require a
   read-only dry run listing every affected entity and planned change first.
   Show the complete list and wait for the human's explicit “yes” before writing.
   Every write batch must use `halt: 1`.
4. Deletion and stopping business processes always require an item-by-item list
   for human confirmation before execution.

## Base parameters

- **Portal**: `bitrix.express-bankrot.ru`
- **Webhook endpoint**: `${BITRIX_WEBHOOK}`
- **Call format from n8n**: POST to `{endpoint}{METHOD}`

## Deals (CRM Deals)

| Method | Description |
|-------|----------|
| `crm.deal.list` | List deals with a filter |
| `crm.deal.get` | Deal by ID |
| `crm.deal.update` | Update deal fields |
| `crm.deal.add` | Create a deal |

Main funnel: `CATEGORY_ID = 4` (BFL / personal bankruptcy).  
Others: VBFL, PS, Contract termination, One-time services.

## Leads (CRM Leads)

| Method | Description |
|-------|----------|
| `crm.lead.list` | List leads |
| `crm.lead.get` | Lead by ID |
| `crm.lead.update` | Update lead |

## Contacts and companies

| Method | Description |
|-------|----------|
| `crm.contact.list` | List contacts |
| `crm.contact.update` | Update contact |
| `crm.company.list` | List companies |
| `crm.company.update` | Update company |

## Smart Processes

| entityTypeId | Name |
|-------------|----------|
| 1094 | KadArbitr |
| 1122 | EFRSB/Fedresurs |
| 1104 | Employee conversion |
| 1112 | Meeting/contract logs |

Methods:
- `crm.item.list` — with the `entityTypeId` parameter
- `crm.item.get`
- `crm.item.update`
- `crm.item.add`

## Batch API

```
POST ${BITRIX_WEBHOOK}batch
{
  "halt": 0,
  "cmd": {
    "deals": "crm.deal.list?filter[CATEGORY_ID]=4&select[]=ID&select[]=TITLE",
    "contacts": "crm.contact.list?filter[...]=...&select[]=ID"
  }
}
```

Up to 50 commands in a single request.

## Users and permissions

| Method | Description |
|-------|----------|
| `user.get` | Get a user |
| `user.update` | Update a user |
| `im.user.list` | List of chat users |
| `bizproc.workflow.instances` | List of running BPs |

## Business processes

| Method | Description |
|-------|----------|
| `bizproc.workflow.start` | Start a BP |
| `bizproc.workflow.terminate` | Stop a BP |
| `bizproc.workflow.template.list` | List of templates |
| `bizproc.task.list` | BP tasks |

⚠️ `bizproc.workflow.template.update` — only via an OAuth app, not via a webhook token.

## Drive (Bitrix Drive)

- Delays: 500ms between folder reads, 3s between writes
- `disk.folder.getchildren` — folder contents
- `disk.file.uploadurl` — file upload

## Filters and pagination

```json
{
  "filter": { "CATEGORY_ID": 4, ">DATE_CREATE": "2024-01-01" },
  "select": ["ID", "TITLE", "ASSIGNED_BY_ID", "STAGE_ID"],
  "order": { "DATE_CREATE": "DESC" },
  "start": 0
}
```

To retrieve all records: iterate over `start` in steps of 50.
