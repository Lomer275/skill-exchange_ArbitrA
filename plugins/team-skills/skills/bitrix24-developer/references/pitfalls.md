# Bitrix24 + n8n — Known Pitfalls & Gotchas

## Bitrix24 API Pitfalls

### 1. bizproc.workflow.template.add/update — ACCESS_DENIED
**Problem:** Webhook tokens cannot create/update BP templates.
**Root cause:** These methods require OAuth app context.
**Workaround:** Templates must be created/edited via Bitrix24 UI. Cannot be automated via REST webhook.
**Affects:** "График Ипотека" BP (ID 1400) and all UI-imported templates.

### 2. BP Document ID format
**Problem:** Wrong document ID format causes BP start to fail silently.
**Correct formats:**
```
Deal:    ["crm", "CCrmDocumentDeal", "456"]       ← ID must be string
Lead:    ["crm", "CCrmDocumentLead", "123"]
Contact: ["crm", "CCrmDocumentContact", "789"]
Smart:   ["crm", "Bitrix\\Crm\\Integration\\BizProc\\Document\\Dynamic", "101"]
```
Note: Some versions require numeric ID, some require string. Test both if issues arise.

### 3. crm.deal.list returns max 50 records
**Problem:** Filter returns only first 50, `total` field shows actual count.
**Fix:** Always implement pagination using `response.next` offset.

### 4. Smart process field names are camelCase
**Problem:** crm.item.list returns `assignedById` not `ASSIGNED_BY_ID`.
**Rule:** Smart processes use camelCase. Deals/leads/contacts use UPPER_CASE.

### 5. Stage IDs differ between funnels
**Problem:** `STAGE_ID: "C4:1"` is funnel-specific. Stage code "1" only exists in funnel 4.
**Debug:** Use `crm.status.list` with filter `ENTITY_ID: "DEAL_STAGE_C{categoryId}"` to get actual stage IDs.

### 6. Custom field names are portal-specific
**Problem:** UF_CRM_* field names are generated per portal and are not transferable.
**Debug:** Use `crm.deal.fields` or `crm.deal.userfield.list` to get actual field names.

### 7. batch result_error is not an exception
**Problem:** If `halt: 0`, failed commands in batch don't throw — check `result.result_error`.
**Fix:**
```javascript
const errors = response.result.result_error;
if (errors && Object.keys(errors).length > 0) {
  console.error('Batch errors:', JSON.stringify(errors));
}
```

### 8. Disk API rate limiting
**Problem:** Too many folder read/write operations → HTTP 503 or silent failures.
**Fix:** 500ms delay between folder reads, 3000ms between folder writes.

### 9. crm.item.list stage filter format
**Problem:** Using UPPER_CASE `STAGE_ID` doesn't work for smart processes.
**Correct:** `{ "stageId": "DT1094_4:NEW" }` (camelCase)

### 10. user.update requires FIELDS wrapper
**Problem:** `user.update?ID=15&NAME=...` doesn't work.
**Correct:**
```json
{ "ID": 15, "FIELDS": { "NAME": "Иван", "UF_DEPARTMENT": [5] } }
```

---

## n8n Pitfalls

### 1. n8n cannot call its own webhooks
**Problem:** HTTP Request node calling `https://n8n.arbitra.online/webhook/...` from within n8n → timeout or loop.
**Fix:** Use "Execute Workflow" node + "When Executed by Another Workflow" trigger for inter-workflow calls.

### 2. Code node timeout (300 seconds)
**Problem:** Large JavaScript loops (e.g., updating 500 records one by one) hit 300s task runner timeout.
**Fix:** Use SplitInBatches node pattern instead of loops in Code nodes.

### 3. IF node — disconnected FALSE branch
**Problem:** If FALSE branch is not connected, workflow stops silently for non-matching items.
**Fix:** Always connect both branches. Use NoOp node for the branch you want to skip.
**Also:** Enable "Always Output Data" on IF nodes.

### 4. EAI_AGAIN DNS errors
**Problem:** Docker n8n intermittently fails to resolve `bitrix.express-bankrot.ru`.
**Fix:** Add `dns: [8.8.8.8, 1.1.1.1]` and `extra_hosts` to docker-compose.yml.

### 5. Webhook trigger URL changes after workflow clone
**Problem:** Cloning a workflow generates a new webhook URL.
**Fix:** Always copy the webhook URL from the actual trigger node after cloning.

### 6. Empty array crashes Code node
**Problem:** `$input.all()` returns empty array → `.map()` or index access crashes.
**Fix:**
```javascript
const items = $input.all();
if (!items || items.length === 0) return [{ json: { skipped: true } }];
```

### 7. Supabase DNS flapping
Same EAI_AGAIN issue as Bitrix. Same fix: explicit DNS + extra_hosts.

---

## DDoS-Guard / kad.arbitr.ru Pitfalls

### FlareSolverr "Challenge not detected!" is not reliable
**Problem:** FlareSolverr reports success even when the actual request fails (returns Chrome error HTML).
**Root cause:** DDoS-Guard blocks by IP at network level before challenge is served.
**Symptom:** Response contains `<title>Ошибка</title>` Chrome error page, not actual data.
**Fix:** Use Playwright/Chromium running locally (Python Flask on port 5055), execute fetch() from within browser context to inherit browser fingerprint.

### Playwright endpoint for kad.arbitr.ru
```
POST http://localhost:5055/search
Body: { "number": "А40-123456/2024" }
```
Service executes fetch() from within Chromium → bypasses DDoS-Guard naturally.

---

## Bitrix24 BI Constructor Limitations

- Apache Superset 4.0 / TRINO backend
- REST API (`biconnector` scope) only exposes resources created by the same webhook context
- Cannot access existing dashboards created via UI through REST API

---

## Bitrix24 Learning Module

- No REST API support
- Workaround requires custom PHP using `CCourse::Add()` / `CLearnLesson::Add()`
- Or iblock-based storage as alternative

---

## Performance Checklist

Before deploying any mass-update workflow:
- [ ] Using SplitInBatches instead of Code loops?
- [ ] Batch requests used (50 ops per call)?
- [ ] Retry on Fail enabled on all HTTP nodes?
- [ ] Rate limiting delays added?
- [ ] Empty result handling in Code nodes?
- [ ] Both IF branches connected?
- [ ] DNS fix applied if using Docker?
