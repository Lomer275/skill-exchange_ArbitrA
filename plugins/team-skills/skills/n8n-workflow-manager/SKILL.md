---
name: n8n-workflow-manager
description: >
  Manage n8n workflows: search, inspect, create, edit, update nodes/connections,
  activate/deactivate, and execute workflows. Use this skill whenever the user asks
  to create a new workflow, edit an existing workflow, add or modify nodes, change
  connections, update credentials, fix a workflow, activate or deactivate a workflow,
  or do anything that involves reading or writing n8n workflow JSON. Also trigger
  when the user says "сделай воркфлоу", "измени воркфлоу", "добавь ноду",
  "отредактируй", "создай workflow", "поправь n8n", or any similar phrase in Russian
  or English about automations in n8n.
---

# n8n Workflow Manager

Skill for reading and modifying n8n workflows at `n8n.arbitra.online`.

---

## Available Tools

### 1. Native n8n MCP Tools (direct access)

| Tool | What it does |
|------|-------------|
| `n8n:search_workflows` | Search by name/description, returns preview list |
| `n8n:get_workflow_details` | Get full JSON of a workflow by ID (nodes, connections, settings) |
| `n8n:execute_workflow` | Execute a workflow (chat / form / webhook input types) |

### 2. Orchestration Proxy (for create/update/delete/activate)

The workflow **"Workflow Manager (MCP Proxy)"** acts as a write API.
Execute it via `n8n:execute_workflow` with `workflowId: ZQ5vm2rASsrCzXUTk3oIw`.

**Input format** (chat trigger):
```json
{
  "action": "...",
  "workflow_id": "...",
  "workflow_data": { ... }
}
```

**Supported actions:**

| action | Required fields | Description |
|--------|-----------------|-------------|
| `list` | — | List all workflows |
| `get` | `workflow_id` | Full JSON of one workflow |
| `create` | `workflow_data` | Create a new workflow |
| `update` | `workflow_id` + `workflow_data` | Replace workflow JSON |
| `delete` | `workflow_id` | Delete workflow |
| `activate` | `workflow_id` | Activate workflow |
| `deactivate` | `workflow_id` | Deactivate workflow |

**How to call:**
```
n8n:execute_workflow(
  workflowId: "ZQ5vm2rASsrCzXUTk3oIw",
  inputs: {
    type: "chat",
    chatInput: JSON.stringify({ action: "...", workflow_id: "...", workflow_data: {...} })
  }
)
```

---

## Standard Workflow

### Reading a workflow
1. If you don't know the ID → `n8n:search_workflows(query: "name")` → find ID
2. `n8n:get_workflow_details(workflowId)` → full JSON

### Modifying a workflow
1. Get current JSON via `get_workflow_details`
2. Make changes in-memory (nodes array, connections object, settings)
3. Send full modified JSON via proxy `action: "update"`
4. Verify: `get_workflow_details` again to confirm

### Creating a workflow from scratch
1. Build the workflow JSON (see structure below)
2. Call proxy `action: "create"` with `workflow_data`
3. If it should be active → call `action: "activate"` on the new ID

---

## Workflow JSON Structure

```json
{
  "name": "Workflow Name",
  "active": false,
  "nodes": [...],
  "connections": {...},
  "settings": { "executionOrder": "v1" },
  "staticData": null
}
```

### Node structure
```json
{
  "id": "uuid-here",
  "name": "Node Display Name",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2,
  "position": [x, y],
  "parameters": { ... },
  "credentials": {
    "credentialTypeName": { "id": "cred_id", "name": "Cred Name" }
  }
}
```

### Connections structure
```json
{
  "Source Node Name": {
    "main": [
      [{ "node": "Target Node Name", "type": "main", "index": 0 }]
    ]
  }
}
```

---

## Common Node Types

| Type string | typeVersion | Use case |
|-------------|-------------|----------|
| `n8n-nodes-base.httpRequest` | 4.2 | HTTP calls |
| `n8n-nodes-base.code` | 2 | JS code (always use v2) |
| `n8n-nodes-base.if` | 2 | Condition branching |
| `n8n-nodes-base.splitInBatches` | 3 | Batch processing loops |
| `n8n-nodes-base.wait` | 1.1 | Delays |
| `n8n-nodes-base.telegram` | 1.2 | Telegram messages |
| `n8n-nodes-base.webhook` | 2 | Incoming webhooks |
| `n8n-nodes-base.scheduleTrigger` | 1.2 | Cron schedule |
| `@n8n/n8n-nodes-langchain.manualChatTrigger` | 1.1 | Chat trigger |
| `n8n-nodes-base.executeWorkflow` | 1.1 | Run sub-workflow |
| `n8n-nodes-base.noOp` | 1 | No-op / passthrough |

---

## Environment-Specific Knowledge

### Bitrix24 HTTP calls
- Webhook base: `https://bitrix.express-bankrot.ru/rest/30351/rzoev7lscjxgq9i6/`
- Batch API: `METHOD: batch` + `PARAMS: {"halt":0,"cmd":{...}}` — up to 50 ops
- Add Retry on Fail (5 retries, 3000ms) on all Bitrix HTTP nodes (DNS flapping)

### Code node rules
- Always `typeVersion: 2`
- HTTP inside Code: `this.helpers.httpRequest()` with try/catch + retry logic
- Avoid large loops in Code → use `SplitInBatches` (prevents 300s timeout)

### IF node rules
- Enable "Always Output Data" on both branches
- Always connect both true/false branches to prevent dead ends

### Sub-workflow communication
- n8n cannot call its own webhooks internally
- Pattern: `executeWorkflow` node + `When Executed by Another Workflow` trigger

### Disk/delays
- Bitrix disk reads: 500ms between folder reads
- Bitrix disk writes: 3s between folder writes

---

## Tips & Gotchas

- **Always fetch current JSON before updating** — never guess node IDs
- **Connections use node display names**, not IDs
- **Node IDs** must be unique UUIDs — generate new ones for new nodes
- Position nodes at logical intervals, e.g. `[250,300]`, `[500,300]` etc.
- After `update`, active/inactive state is preserved → use `activate` separately
- Never modify the proxy workflow `ZQ5vm2rASsrCzXUTk3oIw` through itself

---

## Key Workflow IDs

| Workflow | ID |
|----------|----|
| Workflow Manager (MCP Proxy / orchestrator) | `ZQ5vm2rASsrCzXUTk3oIw` |
| КадАрбитр scraper | `bMN2iJsefpw3DCyi` |
| Bitrix24 Explorer for Claude | `fsX-zC0M_SUTbcCUowIxY` |

---

## Example: Add Telegram notification to existing workflow

```
1. get_workflow_details("target-id")  → current JSON
2. Append to nodes[]:
   {
     "id": "<new-uuid>",
     "name": "Notify Telegram",
     "type": "n8n-nodes-base.telegram",
     "typeVersion": 1.2,
     "position": [last_x + 250, y],
     "parameters": {
       "chatId": "-100xxxxxxxxx",
       "text": "={{ $json.message }}",
       "operation": "sendMessage"
     },
     "credentials": { "telegramApi": { "id": "...", "name": "Telegram" } }
   }
3. Add connection: "Previous Node" → "Notify Telegram"
4. proxy action="update", workflow_id="target-id", workflow_data=<modified>
```
