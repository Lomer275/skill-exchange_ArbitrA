# Business Processes (Bizproc) Reference

All writes must follow the [Write policy](../SKILL.md#write-policy-mandatory).

## Key limitation ⚠️
`bizproc.workflow.template.add/update` requires **OAuth application** context.
Webhook tokens return `ACCESS_DENIED`. Templates imported via Bitrix24 UI cannot be
modified programmatically. Only templates originally created via API by the same OAuth app
can be updated via API.

## Document ID formats

| Entity | Format |
|--------|--------|
| Deal | `["crm", "CCrmDocumentDeal", "DEAL_{id}"]` |
| Lead | `["crm", "CCrmDocumentLead", "LEAD_{id}"]` |
| Contact | `["crm", "CCrmDocumentContact", "CONTACT_{id}"]` |
| Company | `["crm", "CCrmDocumentCompany", "COMPANY_{id}"]` |
| Smart Process | `["crm", "CCrmDocumentItem{entityTypeId}", "{entityTypeId}_{id}"]` |
| Task | `["tasks", "CCrmDocumentTask", "TASK_{id}"]` |

Smart process example: entityTypeId=1094, item id=555:
`["crm", "CCrmDocumentItem1094", "1094_555"]`

## Start Business Process

```json
METHOD: bizproc.workflow.start
PARAMS: {
  "TEMPLATE_ID": 123,
  "DOCUMENT_ID": ["crm", "CCrmDocumentDeal", "DEAL_456"],
  "PARAMETERS": {
    "Variable1": "value1"
  }
}
```
Returns: `{"result": "workflow_instance_id"}`

## List BP Templates

```json
METHOD: bizproc.workflow.template.list
PARAMS: {
  "select": ["ID", "NAME", "DOCUMENT_TYPE", "AUTO_EXECUTE"],
  "filter": {}
}
```
DOCUMENT_TYPE examples:
- `["crm", "CCrmDocumentDeal", "DEAL"]`
- `["crm", "CCrmDocumentItem1094", "DYNAMIC_1094"]`

## List Running Workflow Instances

```json
METHOD: bizproc.workflow.instances.list
PARAMS: {
  "select": ["ID", "WORKFLOW_TEMPLATE_ID", "DOCUMENT_ID", "STARTED", "STARTED_BY"],
  "filter": {
    "DOCUMENT_ID": "DEAL_456"
  }
}
```

## Terminate Workflow

**Warning: stopping a BP interrupts work.** Read the instance first, show its ID,
document and “running → terminated”, and wait for explicit human confirmation
of this item before using the signature below, subject to the Write policy.

```json
METHOD: bizproc.workflow.terminate
PARAMS: {
  "ID": "workflow_instance_id",
  "STATUS": "Terminated by admin"
}
```

## Kill All Workflows on Document

Pattern for n8n:
1. Read-only dry run: `bizproc.workflow.instances.list` with DOCUMENT_ID filter,
   following all pages. Do not terminate anything yet.
2. Show every instance ID, document ID, method `bizproc.workflow.terminate`, and
   “running → terminated” as an item-by-item confirmation list.
3. Wait for the human's explicit “yes” to that exact list; use the sandbox first
   if available and follow the production write route in the Write policy.
4. Terminate only the approved instances. Any write batch uses `halt: 1`;
   stop the whole workflow on an error and read back the resulting state.

## Activity (BP Tasks) — User Tasks in BP

```json
# Get pending BP tasks for user
METHOD: bizproc.task.list
PARAMS: {
  "filter": {"USER_ID": 45, "STATUS": 0},
  "select": ["ID", "WORKFLOW_ID", "DOCUMENT_ID", "NAME", "DESCRIPTION"]
}

# Complete BP task (approve)
METHOD: bizproc.task.complete
PARAMS: {
  "TASK_ID": 789,
  "STATUS": "yes",
  "COMMENT": "Approved"
}
```

STATUS values: `"yes"`, `"no"`, `"ok"`, `"cancel"` — depends on BP task type.

## BP Variables & Constants

```json
# Get workflow template variables
METHOD: bizproc.workflow.template.list
PARAMS: {"select": ["ID", "NAME", "PARAMETERS", "VARIABLES", "CONSTANTS"]}
```

## Auto-start flags
- `AUTO_EXECUTE = 0` — manual only
- `AUTO_EXECUTE = 1` — on create
- `AUTO_EXECUTE = 2` — on update
- `AUTO_EXECUTE = 3` — on create + update

## Bitrix24 BP: 151 templates in portal
- 49 on deals
- 20 on leads  
- 14 on smart processes (across 23 smart process types)
