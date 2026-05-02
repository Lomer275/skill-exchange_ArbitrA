# n8n ↔ Bitrix24 Integration Patterns

## Environment
- n8n: `n8n.arbitra.online` (self-hosted, Docker)
- Bitrix webhook: `https://<YOUR_BITRIX_PORTAL>/rest/<USER_ID>/<WEBHOOK_TOKEN>/`
- Explorer workflow: `<N8N_BRIDGE_WORKFLOW_ID>`
- Orchestrator/MCP workflow: `ZQ5vm2rASsrCzXUTk3oIw`

---

## HTTP Request Node — Standard Config

```
Method: POST
URL: https://<YOUR_BITRIX_PORTAL>/rest/<USER_ID>/<WEBHOOK_TOKEN>/crm.deal.list
Authentication: None (webhook has auth built in)
Body Content Type: JSON
Body: {
  "filter": {"CATEGORY_ID": 4},
  "select": ["ID", "TITLE", "STAGE_ID"],
  "start": 0
}
```

Enable: **Retry on Fail** → 5 retries, 3000ms delay (DNS flapping fix).

---

## Pagination Pattern

```
[Webhook/Manual trigger]
  → [Set node: start = 0]
  → [HTTP Request: crm.deal.list with start={{$json.start}}]
  → [IF: response.next exists]
      YES → [Set: start = {{$json.next}}] → loop back to HTTP
      NO  → [Merge all results] → continue
```

In Code node:
```javascript
const items = $input.all();
const allDeals = items.flatMap(i => i.json.result || []);
return allDeals.map(deal => ({json: deal}));
```

---

## Batch API Pattern in n8n

Instead of 50 HTTP calls, use 1 batch:
```javascript
// In Code node - build batch command
const ids = $input.all().map(i => i.json.ID);
const cmd = {};
ids.slice(0, 50).forEach((id, idx) => {
  cmd[`deal_${idx}`] = `crm.deal.get?id=${id}`;
});

return [{json: {cmd}}];
```

Then HTTP Request:
```
URL: .../batch
Body: {"halt": 0, "cmd": {{$json.cmd}}}
```

Parse response:
```javascript
const result = $input.first().json.result.result;
// result is object: {deal_0: {...}, deal_1: {...}}
return Object.values(result).map(deal => ({json: deal}));
```

---

## SplitInBatches Pattern (large updates)

For updating 100+ records without hitting 300s timeout:

```
[Array of IDs]
  → [SplitInBatches: batchSize=50]
  → [Code/HTTP: process batch]
  → [Wait: 500ms]
  → [SplitInBatches: loop back if hasMore]
```

**Never** use `for` loops in Code nodes for >50 records — use SplitInBatches.

---

## Code Node HTTP Helper (resilient)

```javascript
async function bitrixRequest(method, params, retries = 5) {
  const delay = ms => new Promise(r => setTimeout(r, ms));
  
  for (let i = 0; i < retries; i++) {
    try {
      const response = await this.helpers.httpRequest({
        method: 'POST',
        url: `https://<YOUR_BITRIX_PORTAL>/rest/<USER_ID>/<WEBHOOK_TOKEN>/${method}`,
        body: params,
        json: true,
      });
      return response;
    } catch (err) {
      if (i === retries - 1) throw err;
      await delay(5000);
    }
  }
}

// Usage
const result = await bitrixRequest.call(this, 'crm.deal.list', {
  filter: { CATEGORY_ID: 4 },
  select: ['ID', 'TITLE']
});
return result.result.map(deal => ({json: deal}));
```

**Note**: Code nodes use `typeVersion: 2`. Always use `this.helpers.httpRequest()`.

---

## Daily/Weekly Report Pattern

Used in "Ежедневный отчёт" workflow:

```javascript
// section() with try/catch — REQUIRED pattern
function section(title, items) {
  try {
    if (!items || items.length === 0) return null;
    const lines = items.map(i => `• ${i.name}: ${i.value}`).join('\n');
    return `*${title}*\n${lines}`;
  } catch(e) {
    return null;
  }
}

const sections = [
  section('Стадия 1', stage1Items),
  section('Стадия 2', stage2Items),
].filter(Boolean); // REQUIRED - remove nulls

const message = sections.join('\n\n');
```

**IF nodes**: Enable "Always Output Data" to prevent broken connections.
**All HTTP nodes** (including contact fetch): must be connected to final Code node.

---

## Webhook Trigger from Bitrix24

Bitrix sends POST with form-encoded body:
```
event=ONCRMDEALUPDATE
data[FIELDS_AFTER][ID]=456
data[FIELDS_AFTER][STAGE_ID]=C4:3
auth[domain]=<YOUR_BITRIX_PORTAL>
```

Parse in n8n:
```javascript
const data = $input.first().json.body;
const dealId = data['data[FIELDS_AFTER][ID]'];
const stageId = data['data[FIELDS_AFTER][STAGE_ID]'];
```

Or use n8n's built-in parsing: `$input.first().json.data.FIELDS_AFTER.ID`

---

## Inter-workflow Communication

**RULE**: n8n cannot call its own webhooks internally.

Use instead:
- "Execute Workflow" node → target workflow's "When Executed by Another Workflow" trigger
- Pass data via `items` array

---

## DNS Flapping Fix (Docker)

`docker-compose.yml` additions:
```yaml
services:
  n8n:
    dns:
      - 8.8.8.8
      - 1.1.1.1
    extra_hosts:
      - "<YOUR_BITRIX_PORTAL>:SERVER_IP"
```

All HTTP nodes to Bitrix: enable Retry on Fail, 5 retries, 3000ms delay.

---

## Telegram Report Formatting

```javascript
// Escape special chars for MarkdownV2
function esc(text) {
  return String(text).replace(/[_*[\]()~`>#+\-=|{}.!]/g, '\\$&');
}

// Or use HTML parse mode (easier)
const message = `<b>Отчёт за ${date}</b>\n\n<b>Main pipeline (example)</b>\n• Новые: ${newCount}`;
// Send with parse_mode: HTML
```

---

## Common Workflow Structures in Portal

1. **Web-scraper (example)** — `<EXAMPLE_WORKFLOW_ID>` (DDoS-Guard bypass)
2. **Ежедневный отчёт** — smart process meetings → Telegram grouped by stage
3. **Bitrix увольнение** — employee termination: transfer activities, tasks, deals
4. **Explorer** — `<N8N_BRIDGE_WORKFLOW_ID>` — single API call bridge for Claude

---

## Увольнение (Termination) Workflow Pattern

Transfer checklist for fired employee:
1. Activities (`crm.activity.list` → `crm.activity.update` RESPONSIBLE_ID)
2. Tasks (`tasks.task.list` → `tasks.task.update` RESPONSIBLE_ID)  
3. Deals (`crm.deal.list` → `crm.deal.update` ASSIGNED_BY_ID)
4. Contacts/Companies (`crm.contact.list` → `crm.contact.update`)
5. Access rights removal (`user.update` with `UF_DEPARTMENT` change or deactivation)

Performance: use SplitInBatches(50) + batch API, not sequential updates with 5s waits.
