---
name: codereview
description: >
  Multi-phase, meticulous code review of a task. Use this skill whenever
  the user asks to check code, do a review, find bugs, verify
  acceptance criteria, or says "/codereview", "сделай ревью", "проверь код",
  "посмотри что не так", "найди баги", "code review". The skill covers all phases:
  acceptance criteria check, adversarial review, user walkthrough, architectural
  fit. The result is a structured table of findings with severity and an entry in the task file.
---

# Code Review Skill

A meticulous, multi-phase review of a task's code. Analysis only — no fixes.

---

## Input data

The user provides one or more of:
- A task file (with acceptance criteria)
- Changed code files (pasted into the chat or uploaded)
- A task number (`T01`, `T02`, …) for identification

If nothing is provided — ask for the task file and the changed files.

---

## Execution algorithm

### 0. Context gathering

1. Find and read the **task file** — you need:
   - Acceptance Criteria
   - The task description
   - The affected files (if specified)

2. Read **all the provided code files** — changed + contextual ones (routing, layout, store, config, downstream components).

3. If the user mentioned a task number but did not attach files — ask for them explicitly.

---

### Phase A — Acceptance criteria check

For each acceptance criterion from the task file:
- Find the corresponding code
- Render a verdict: ✅ met / ❌ not met / ⚠️ partial
- For ❌ and ⚠️ — point to the specific line/file and explain what is wrong

Format:
```
| # | Критерий | Статус | Комментарий |
|---|----------|--------|-------------|
| 1 | ... | ✅ | — |
| 2 | ... | ❌ | file.ts:42 — не обрабатывается случай X |
```

---

### Phase B — Adversarial Review

Ask yourself: **"How will this code break?"**

Check by category:

**Correctness:**
- Boundary cases (empty array, null, 0, a very large number)
- Race conditions, async/await errors
- Incorrect assumptions about data types

**Security:**
- XSS, injections, unsafe deserialization
- Exposed secrets or tokens in the code
- Insecure defaults

**API contract:**
- Conformance to the expected interface (types, fields, response format)
- Breaking changes for the calling code

**Performance:**
- N+1 queries
- Heavy operations in render / hot path
- Memory leaks (unclosed subscriptions, listeners)

**Dead code:**
- Unused imports, variables, functions
- Commented-out code

---

### Phase C — User Walkthrough

Mentally walk through **3–5 user scenarios** across the changed code:

1. Happy path — everything works as intended
2. Empty state — no data / first launch
3. Error state — the server returned an error / the network is unavailable
4. Edge case — non-standard user input
5. Concurrent actions — the user clicked a button twice

For each scenario: describe what happens, and point out the problem if there is one.

Also check the **outgoing links**: all API endpoints, routes, imports — do they exist?

---

### Phase D — Architectural fit

- Does the change fit into the existing architecture?
- Does it create technical debt that will block the next tasks?
- Are the project's adopted patterns followed (if known)?

---

## Classification of findings

| Severity | When |
|----------|-------|
| **CRITICAL** | Application crash, data loss, security vulnerability |
| **HIGH** | Incorrect behavior, acceptance criterion violation, blocker |
| **MEDIUM** | Edge case, poor UX, dead code, tech debt |
| **LOW** | Style, naming, minor improvements |

---

## Output format

### Summary

```
## Code Review — [Название задачи / ID]

**Критерии приёмки:** X/Y выполнено
**Найдено:** N CRITICAL, M HIGH, K MEDIUM, L LOW
**Вердикт:** ✅ Готово к принятию / ⚠️ Требует фиксов / ❌ Заблокировано
```

### Findings table

```
| ID | Severity | Фаза | Файл:строка | Описание | Рекомендация |
|----|----------|------|-------------|----------|--------------|
| R1 | CRITICAL | B | api/users.ts:34 | SQL injection через прямую подстановку | Использовать параметризованные запросы |
| R2 | HIGH | A | store/auth.ts | AC#3 не выполнен — logout не очищает токен | Добавить clearToken() в logout() |
| R3 | MEDIUM | C | UserList.tsx | Empty state не обработан — падает на .map() | Проверить array на undefined перед map |
```

### Details for each finding (for CRITICAL and HIGH)

A brief explanation + a concrete code example where the problem is.

---

## Rules

- **Analysis only** — do not propose ready-made fix code (that's what `/fix` does)
- Be specific: always point to the file and line where the problem is
- If code was not provided for some criterion — mark it as ⚠️ "not checked"
- Compare with the previous review if there is one in the task file — note regressions
- If the task has no acceptance criteria — report this and do only phases B, C, D

---

## See also

- **`/codereview-dual`** — a dual independent review with Codex as a second lens (correctness/edge-cases/risks). Routing selects it automatically if Codex is available and `enabled: true` in `.claude/codex.json`. See spec S11.
- **`/codex-toggle`** — switching between classic review and dual.
- **`/review-loop`** — the `codereview → fix` loop until clean of CRITICAL/HIGH.
- **`/fix`** — applying fixes from the findings table.
