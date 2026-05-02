# Node Templates — Готовые шаблоны параметров

## Webhook Trigger

```json
{
  "id": "{{uuid}}",
  "name": "Webhook",
  "type": "n8n-nodes-base.webhook",
  "typeVersion": 2,
  "position": [240, 300],
  "parameters": {
    "httpMethod": "POST",
    "path": "my-endpoint",
    "responseMode": "lastNode",
    "options": {}
  },
  "webhookId": "{{uuid}}"
}
```

## Schedule Trigger (каждый день в 09:00)

```json
{
  "id": "{{uuid}}",
  "name": "Schedule Trigger",
  "type": "n8n-nodes-base.scheduleTrigger",
  "typeVersion": 1.2,
  "position": [240, 300],
  "parameters": {
    "rule": {
      "interval": [{ "field": "cronExpression", "expression": "0 9 * * 1-5" }]
    }
  }
}
```

## HTTP Request (POST JSON)

```json
{
  "id": "{{uuid}}",
  "name": "HTTP Request",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2,
  "position": [460, 300],
  "parameters": {
    "method": "POST",
    "url": "https://example.com/api",
    "authentication": "none",
    "sendBody": true,
    "contentType": "json",
    "specifyBody": "json",
    "jsonBody": "={{ JSON.stringify($json) }}",
    "options": {
      "response": { "response": { "fullResponse": false } }
    }
  },
  "retryOnFail": true,
  "maxTries": 5,
  "waitBetweenTries": 3000
}
```

## Code Node (JS, typeVersion 2)

```json
{
  "id": "{{uuid}}",
  "name": "Code",
  "type": "n8n-nodes-base.code",
  "typeVersion": 2,
  "position": [460, 300],
  "parameters": {
    "jsCode": "const items = $input.all();\nconst result = [];\n\nfor (const item of items) {\n  result.push({ json: { ...item.json } });\n}\n\nreturn result;"
  }
}
```

## IF Node

```json
{
  "id": "{{uuid}}",
  "name": "IF",
  "type": "n8n-nodes-base.if",
  "typeVersion": 2,
  "position": [460, 300],
  "parameters": {
    "conditions": {
      "options": { "caseSensitive": true, "leftValue": "", "typeValidation": "strict" },
      "conditions": [
        {
          "id": "{{uuid}}",
          "leftValue": "={{ $json.status }}",
          "rightValue": "active",
          "operator": { "type": "string", "operation": "equals" }
        }
      ],
      "combinator": "and"
    },
    "options": { "alwaysOutputData": true }
  }
}
```

## Set Node

```json
{
  "id": "{{uuid}}",
  "name": "Set",
  "type": "n8n-nodes-base.set",
  "typeVersion": 3.4,
  "position": [460, 300],
  "parameters": {
    "mode": "manual",
    "fields": {
      "values": [
        { "name": "fieldName", "type": "stringValue", "stringValue": "={{ $json.source }}" }
      ]
    },
    "include": "none",
    "options": {}
  }
}
```

## SplitInBatches

```json
{
  "id": "{{uuid}}",
  "name": "Split In Batches",
  "type": "n8n-nodes-base.splitInBatches",
  "typeVersion": 3,
  "position": [460, 300],
  "parameters": {
    "batchSize": 10,
    "options": { "reset": false }
  }
}
```

## Wait Node (5 секунд)

```json
{
  "id": "{{uuid}}",
  "name": "Wait",
  "type": "n8n-nodes-base.wait",
  "typeVersion": 1,
  "position": [680, 300],
  "parameters": {
    "amount": 5,
    "unit": "seconds"
  },
  "webhookId": "{{uuid}}"
}
```

## Telegram Send Message

```json
{
  "id": "{{uuid}}",
  "name": "Telegram",
  "type": "n8n-nodes-base.telegram",
  "typeVersion": 1.2,
  "position": [680, 300],
  "parameters": {
    "chatId": "={{ $json.chatId }}",
    "text": "={{ $json.message }}",
    "additionalFields": {
      "parse_mode": "Markdown",
      "disable_notification": false
    }
  },
  "credentials": {
    "telegramApi": { "id": "{{cred_id}}", "name": "Telegram Bot" }
  }
}
```

## Execute Workflow (вызов другого воркфлоу)

```json
{
  "id": "{{uuid}}",
  "name": "Execute Workflow",
  "type": "n8n-nodes-base.executeWorkflow",
  "typeVersion": 1.1,
  "position": [460, 300],
  "parameters": {
    "workflowId": { "__rl": true, "value": "{{target_workflow_id}}", "mode": "id" },
    "waitForSubWorkflow": true,
    "options": {}
  }
}
```

## When Executed by Another Workflow (триггер)

```json
{
  "id": "{{uuid}}",
  "name": "When Executed by Another Workflow",
  "type": "n8n-nodes-base.executeWorkflowTrigger",
  "typeVersion": 1.1,
  "position": [240, 300],
  "parameters": { "inputSource": "parentWorkflow" }
}
```
