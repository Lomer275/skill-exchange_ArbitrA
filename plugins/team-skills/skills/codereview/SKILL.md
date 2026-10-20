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

0. **Check which tree you are reviewing** — before reading any code, from the repo root:
   ```bash
   git fetch --quiet origin main || echo "FETCH FAILED: origin/main below is not fresh"
   git log -1 --format='origin/main tip: %h %cd' --date=short origin/main
   git rev-parse --abbrev-ref HEAD; pwd; git rev-list --left-right --count origin/main...HEAD; git status --porcelain | wc -l
   ```
   The counts are `<behind> <ahead>` and the number of dirty entries. A tree behind main is a snapshot, not what runs in prod: what main has and the tree lacks looks missing or broken. A dirty tree mixes in other people's uncommitted work, however fresh the branch is.
   - **The change** is the files the user or the task names, compared with the point the branch forked from: `git diff $(git merge-base origin/main HEAD) -- <files>` (an untracked file is new in full — read it whole). Not `git diff origin/main`: on a tree behind main, main's newer commits show up as reverse edits. Dirty files nobody named are not the change — except, inside a review loop, the files that loop's own `/fix` runs changed: the loop names them, and they are part of the change, so a regression a fix brought into another file is sorted as a finding about the change, not a phantom. **Dirty outside the change** is the count without the change's own files: `git status --porcelain -- . ':(exclude)<file1>' ':(exclude)<file2>' | wc -l` — this number, not the total, goes into the «Дерево» line and decides the sorting below.
   - **A finding about the change's own lines** stays. If the tree is behind main or dirty outside the change and the finding rests on something read from disk — a rule, a flag, a helper, a migration — confirm that premise on main first; false there → a phantom (below).
   - **Every other finding** is sorted before it is reported. On a tree 0 behind, 0 ahead, with nothing dirty outside the change, the code outside the change is main's own: case 1, no check needed. 0 behind and nothing dirty outside the change, but ahead → only the branch's own commits can differ from main: `git diff $(git merge-base origin/main HEAD) HEAD -- "<path>"` touches the finding's lines → case 2, otherwise case 1. Any other tree → check on main: `git grep -n -F "<anchor>" origin/main -- "<path>"`; the path is missing there → `git grep -n -F "<anchor>" origin/main` and `git log --oneline -3 origin/main -- "<path>"` (moved or deleted). Path and anchor both gone → look for a successor before settling on case 2 or 3 (a branch whose work was squash-merged lands on main under new names): `git log origin/main --oneline -S"<distinctive identifier>" | head -3`, or `git ls-tree -r --name-only origin/main | grep -i "<stem>"`; found → sort by that code. Read the enclosing function on main — never drop on a failed grep alone, code gets reformatted and moved — then:
     1. main has the same defect → a real bug, older than the change: ID `OLD-<n>`, its own table (Output format);
     2. main has it right or no longer has this code, but this branch's own commits changed those lines (`git diff $(git merge-base origin/main HEAD) HEAD -- "<path>"`) → real: keep it, mark «есть только в ветке»;
     3. otherwise — main moved on, or the code is someone's uncommitted work → a phantom of the snapshot: drop it and count it;
     4. could not tell → keep it, mark «не проверено на main».

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

**Silent failures** — only in the lines the change adds or modifies, not a sweep of the whole file:
- `except Exception: pass`, or a broad `except` that neither re-raises nor logs at WARNING or above. A traceback (`logger.exception`, `exc_info=True`) is the norm; where the exception text may carry personal data — a request URL with a person's tax ID — the exception type alone is enough. An `except` with no log, or with a log at DEBUG/INFO, is the finding. Deliberate best-effort cleanup with a comment saying so is not a finding
- On error the code returns `None` / `[]` / `{}` / a default that the callers read as "no data" — the user then sees "nothing found" instead of an outage. A deliberate fail-open that logs a WARNING and says so in a comment is not a finding
- A new HTTP session, or a new request on a session without its own `ClientTimeout`, that sets no explicit timeout (`requests` waits forever by default; a bare `aiohttp.ClientSession()` gives up only after 5 minutes). Calls through a shared client that has no timeout of its own inherit that gap: it is one old bug in the client, not a finding at every call site
- In sync code, a multi-step DB write (several `save` / `create` / `update` that must land together) outside a transaction (`transaction.atomic` in Django)
- Not a finding, when the project's `CLAUDE.md` sets this observability rule: an error nobody can act on (the user blocked the bot or deleted the account) logged as WARNING at its source. The opposite is a finding: such an error logged as ERROR.

**LLM boundary** — when the changed lines call or import the project's model path (its LLM wrappers, an OpenAI or Anthropic client), run the `claude` CLI, or edit a prompt (often a module-level constant such as `SYSTEM_PROMPT`). To find where model calls live, grep for those clients and for `claude` invocations; a `.claude/rules/*.md` file about the AI part may list them in its `paths:`. A change in these files turns the group on only when its lines touch the call, the prompt, the handling of the model's output, or what the user is shown:
- Untrusted text (user messages, OCR of documents, CRM fields, web pages) reaches the prompt as instructions instead of quoted data
- Model output used as a URL, ID, file path, SQL or shell argument without checking it against an allow-list or the user's own records
- Text a user will see is built from someone else's record: data about other people's cases, orders or accounts must come through the project's ownership guard, if it has one, not straight from the raw table. A guard behind a flag, or one that fails open (filters nothing on an error), is no guarantee: code that assumes the guard always ran is a finding too
- A Claude CLI call meant as a pure generator that is not isolated. Isolation is three things: `--tools ""`, `--no-session-persistence`, and an empty temporary cwd so the project's `CLAUDE.md` does not load. A change that drops any of the three, adds `--allowedTools`, or adds a call site without them is a finding. An agent that uses tools by design is not this rule

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
- **Module rules.** For every top-level directory the change touches that has its own `CLAUDE.md`, read it and check the change against the pitfalls listed there. Read main's copy — `git show origin/main:<dir>/CLAUDE.md` — unless the change itself edits that file: the copy on a tree behind main can be wrong.
- **Flags.** If the project keeps a flag registry or flag descriptions (a flags module, `.claude/rules/env-*.md` or the like), look up every env flag the change reads, adds or alters on main, from the repo root: `git grep -n -F FLAG_NAME origin/main`. The registry entry (default, the processes that read it, dependencies) and the description (bans, enable conditions) are the reference; a change that contradicts either is a finding. A description often covers a whole group in one block — search the prefix too before calling a flag undocumented. A flag is new when `git grep -q -F FLAG_NAME origin/main` finds nothing; a new flag — numeric settings included — with no entry where the project documents its flags is a MEDIUM. The rules files on disk may be older than main's: read main's.

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

**Дерево:** <ветка>, <pwd>, позади main: <n>, впереди: <m>, грязных вне изменения: <d>
**Критерии приёмки:** X/Y выполнено
**Найдено:** N CRITICAL, M HIGH, K MEDIUM, L LOW
**Отброшено как фантом устаревшего дерева:** <k>
**Старые баги main (вне изменения):** <o>, не вошли в вердикт
**Вердикт:** ✅ Готово к принятию / ⚠️ Требует фиксов / ❌ Заблокировано
```

Print «Дерево» always; if the fetch failed, end it with «origin/main не обновлён». Print «Отброшено…» only when Step 0 sorted findings against main, and «Старые баги…» only when there is at least one `OLD-` row. `OLD-` rows count neither in «Найдено» nor in the verdict. The Step 0 marks «есть только в ветке» and «не проверено на main» go at the start of the row's «Описание».

### Findings table

```
| ID | Severity | Фаза | Файл:строка | Описание | Рекомендация |
|----|----------|------|-------------|----------|--------------|
| R1 | CRITICAL | B | api/users.ts:34 | SQL injection через прямую подстановку | Использовать параметризованные запросы |
| R2 | HIGH | A | store/auth.ts | AC#3 не выполнен — logout не очищает токен | Добавить clearToken() в logout() |
| R3 | MEDIUM | C | UserList.tsx | Empty state не обработан — падает на .map() | Проверить array на undefined перед map |
```

### Старые баги main (вне изменения) — only if Step 0 found any

Real defects that main has too and the change did not bring in. `/review-loop` does not count them and `/fix` skips them unless asked by ID. They are fixed separately, in a worktree off main: `git worktree add ../<repo>-wt/fix-<slug> -b fix/<slug> origin/main` (`<repo>` — the repository's directory name). Off main, not off a working branch that lags it.

```
| ID | Severity | Файл:строка на main | Описание | Рекомендация |
|----|----------|---------------------|----------|--------------|
| OLD-1 | MEDIUM | path/x.py:120 | <пример формата, не находка> | <что поправить> |
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
