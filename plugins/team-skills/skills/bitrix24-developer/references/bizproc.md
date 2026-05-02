# Business Processes (Bizproc) Reference

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

```json
METHOD: bizproc.workflow.terminate
PARAMS: {
  "ID": "workflow_instance_id",
  "STATUS": "Terminated by admin"
}
```

## Kill All Workflows on Document

Pattern for n8n:
1. `bizproc.workflow.instances.list` with DOCUMENT_ID filter
2. Loop through results
3. `bizproc.workflow.terminate` for each instance ID

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
