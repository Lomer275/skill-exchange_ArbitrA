# n8n ↔ Bitrix24 Integration Patterns

All writes must follow the [Write policy](../SKILL.md#write-policy-mandatory).

## Environment
- n8n: `n8n.arbitra.online` (self-hosted, Docker)
- Bitrix webhook: `${BITRIX_WEBHOOK}`
- Explorer workflow: `fsX-zC0M_SUTbcCUowIxY`
- Orchestrator/MCP workflow: `ZQ5vm2rASsrCzXUTk3oIw`

---

## HTTP Request Node — Standard Config

```
Method: POST
URL: ${BITRIX_WEBHOOK}crm.deal.list
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

First run only reads with pagination to collect every candidate and its current
values. Output the full list of methods, entity IDs and fields “before → after”.
Show it and wait for the human's explicit “yes”. Use the project sandbox first
if available and follow the production write route in the Write policy.
Only the confirmed plan may enter the write phase below:

For updating 100+ approved records without hitting 300s timeout:

```
[Confirmed plan: approved IDs and field changes]
  → [SplitInBatches: batchSize=50]
  → [Code/HTTP: write batch with halt: 1; stop workflow on result_error]
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
        url: `${BITRIX_WEBHOOK}${method}`,
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

Used in the "Daily Report" workflow:

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
auth[domain]=bitrix.express-bankrot.ru
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
      - "bitrix.express-bankrot.ru:SERVER_IP"
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
const message = `<b>Отчёт за ${date}</b>\n\n<b>БФЛ</b>\n• Новые: ${newCount}`;
// Send with parse_mode: HTML
```

---

## Common Workflow Structures in Portal

1. **KadArbitr scraper** — `bMN2iJsefpw3DCyi` (DDoS-Guard bypass)
2. **Daily Report** — smart process meetings → Telegram grouped by stage
3. **Bitrix termination** — employee termination: transfer activities, tasks, deals
4. **Explorer** — `fsX-zC0M_SUTbcCUowIxY` — single API call bridge for Claude

---

## Termination Workflow Pattern

1. Read-only dry run: list all affected activities, tasks, deals, contacts,
   companies, and the employee's current account fields, following all pages.
   Build a per-entity plan with method, ID and every field “before → after”,
   including ownership transfers and account/access changes. No writes yet.
2. Show the full plan and wait for the human's explicit “yes” to that list.
   Use the project sandbox first if available and follow the production write
   route in the Write policy. Do not add targets after confirmation.
3. Only then execute the approved transfer checklist:

- Activities (`crm.activity.list` → `crm.activity.update` RESPONSIBLE_ID)
- Tasks (`tasks.task.list` → `tasks.task.update` RESPONSIBLE_ID)
- Deals (`crm.deal.list` → `crm.deal.update` ASSIGNED_BY_ID)
- Contacts/Companies (`crm.contact.list` → `crm.contact.update`)
- Access rights removal (`user.update` with `UF_DEPARTMENT` change or deactivation)

Write phase: use SplitInBatches(50) + batch API with `halt: 1` and stop the
whole workflow on any `result_error`. Read back results; obtain confirmation
for a revised plan after a partial failure before retrying.
