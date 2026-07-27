---
name: safe-push
description: >
  Safe commit and push in a single command with a mandatory secrets check.
  Use this skill when the user says "/sup-push", "закоммить и запушь",
  "commit and push", "запушь", "запушить", "закоммить". The skill checks staged files
  for secrets (BLOCKS if any are found), builds the commit message per
  Conventional Commits, and commits and pushes with safe error handling.
---

# Sup-Push Skill

Safe commit + push with a blocking secrets check and Conventional Commits format.

---

## Input data

The user provides one or more of:
- **A commit message** (optional) — a string in the chat or after the command
- **A list of files** to add (optional) — if not specified, the already-staged ones are used

If there are no staged files and no files were specified — warn and stop.

---

## Execution algorithm

### Step 1 — Secrets check (BLOCKING)

Run `git diff --staged` and `git status --short`.

**Check the list of staged files for dangerous names:**
- `.env`, `.env.*`, `.env.local`, `.env.production`
- `*.pem`, `*.key`, `*.p12`, `*.pfx`

**Check the contents of staged files for dangerous patterns in string values:**
- `TOKEN\s*=\s*["'][^"']{8,}`
- `API_KEY\s*=\s*["'][^"']{8,}`
- `SECRET\s*=\s*["'][^"']{8,}`
- `PASSWORD\s*=\s*["'][^"']{8,}`
- `-----BEGIN .* PRIVATE KEY-----`

**If found** → FULL STOP. Show:
```
🚫 СТОП — обнаружены секреты в staged-файлах!

Файл: <путь к файлу>
Строка: <номер строки>
Паттерн: <что именно найдено>

Коммит заблокирован. Удали секреты из файла или добавь файл в .gitignore.
Продолжение невозможно даже по явной просьбе.
```
Do not continue under any circumstances, even if the user asks.

**If there are no staged files** → warn and stop:
```
⚠️ Нет staged-файлов для коммита. Добавь файлы через git add или укажи их явно.
```

---

### Step 2 — Building the commit message

Read `docs/4. SUP-guides/versioning_guidelines.md` (at RUNTIME, not from memory) — for the project's current Conventional Commits format.

**Commit format per Conventional Commits:**
```
<тип>(<область>): краткое описание на русском

[опциональное тело]
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `style`, `ci`
Scopes: `tg-bot`, `max-bot`, `handler`, `tracker`, `bitrix`, `ai`, `docs`, `deps` (or any relevant one)

**If the user provided a message:**
1. Check the format — does it conform to Conventional Commits
2. If it does not conform — propose a corrected version
3. Show the final message before committing and wait for confirmation

**If no message was provided:**
1. Run `git diff --staged` and analyze the changes
2. Propose a commit message
3. Show it and wait for the user's confirmation

Display format:
```
📝 Предлагаемое сообщение коммита:

  feat(tg-bot): добавить обработчик my_case для просмотра дела

Подтверди ("ок", "да", "go") или скорректируй текст.
```

---

### Step 3 — Commit

After the message is confirmed:

```bash
# Если пользователь указал конкретные файлы — добавляем их
git add <файлы>

# Коммит
git commit -m "<сообщение>"
```

Show the list of committed files:
```
✅ Закоммичено: <хеш>
Файлы:
  - max_bot/handlers/my_deal.py
  - tg_bot/handlers/menu/my_case.py
  - ...
```

---

### Step 4 — Push

```bash
git push
```

**Scenarios:**

**A. The branch is not tracked by the remote:**
```
⚠️ Ветка <имя> не привязана к remote.
Выполнить: git push -u origin <имя>? (да/нет)
```
Wait for confirmation before executing.

**B. Push rejected (not fast-forward):**
```
❌ Push отклонён — remote содержит коммиты которых нет локально.

Варианты:
  1. git pull --rebase && git push  (рекомендуется)
  2. Показать git log --oneline -10 для анализа

Выбери вариант или напиши своё решение.
```
Do NOT do a force push without an explicit request from the user.
If the user explicitly asks for a force push — warn about the danger and request a repeat confirmation.

**C. Success:**
```
✅ Запушено!

Ветка:   <имя ветки>
Коммит:  <хеш> <сообщение>
Файлов:  <N> изменено
```

---

## Rules

- **Secrets are an absolute block**: a pattern found → stop, no exceptions, even if the user insists
- **Read versioning_guidelines.md at runtime** — do not rely on memory for the commit format
- **Do not commit without confirmation** — always show the message before git commit
- **Never do a force push** without an explicit user request ("force push", "принудительно запушь")
- **On a force push request** — first warn ("this will overwrite the remote history"), then wait for a repeat confirmation
- **Do not add git add -A / git add .** without an explicit user instruction — only specific files
- **Staged without git add** — if the user did not specify files and there are already staged changes, use them

---

## Quick mode

If the user passed the commit message together with the command (for example: "запушь feat(tg-bot): добавить my_case") — you may skip waiting for message confirmation and commit immediately (after the secrets check). Show the summary after the push.
