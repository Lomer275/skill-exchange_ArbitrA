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

**Stage first.** If the user named files, stage exactly those now: `git add -- <файлы>` (never `git add -A` / `git add .`, see Rules). Every check below looks at what is staged, and Step 3 commits exactly that. Nothing staged and no files named → warn and stop:
```
⚠️ Нет staged-файлов для коммита. Добавь файлы через git add или укажи их явно.
```

**Record what is staged.** Step 2 shows this list, and Step 3 compares the sum before committing:

```bash
git diff --staged --name-only; git diff --staged | sha256sum | cut -c1-16
```

The user named files, but the list holds others too (staged earlier) → show the extras and ask whether they go into this commit. Do not commit them silently, and unstage one (`git restore --staged <файл>`) only on the human's word; then record again.

**Is the commit-time gate on?**

```bash
top=$(git rev-parse --show-toplevel); test -x "$top/.githooks/pre-commit" && echo hook=ok || echo hook=MISSING; command -v gitleaks >/dev/null && echo gitleaks=ok || echo gitleaks=MISSING; echo "hooksPath=$(git config --get core.hooksPath)"; echo "skip:${SKIP_GITLEAKS:-no}"
```

The gate is `gitleaks` in `.githooks/pre-commit`, switched on by `core.hooksPath=.githooks`. A project with no such hook on `origin/main` either (`git cat-file -e origin/main:.githooks/pre-commit` fails) has no commit-time gate: say so in one line and go on to the scan below. It is on when the output reads `hook=ok`, `gitleaks=ok`, `hooksPath=.githooks` and anything but `skip:1`. It goes off in four ways, and none of them stops the commit. Two are silent: the hook is absent, or `core.hooksPath` is not `.githooks`. Two print one line at commit time that is easy to miss: no `gitleaks` → the hook's ⚠ warning; `SKIP_GITLEAKS=1` → «gitleaks: проверка пропущена». A hook that is there but not executable counts as absent; git only adds a "hook was ignored" hint.

| Output | Why the gate is off | What to offer |
|---|---|---|
| `hook=MISSING` | the hook is absent or not executable in this branch. When `origin/main` has it, the branch is older than the hook, while `core.hooksPath` sits in the `.git/config` all checkouts share — so the branch commits with no scan: silently when the hook is absent, with git's hint when it is not executable | optional: if this commit needs the gate itself, move the changes to a worktree off `origin/main`, where the hook is in place; otherwise the scan below stands in for it |
| `gitleaks=MISSING` | the hook prints a warning and lets the commit through | installing the binary is the human's job (github.com/gitleaks/gitleaks/releases → `~/.local/bin`) |
| `hooksPath` not `.githooks` | git never calls the hook | the command for the human's own terminal: `git config core.hooksPath .githooks` — it is denied to the agent |
| `skip:1` | `SKIP_GITLEAKS=1` is set in the environment, so the hook skips itself | the human removes it from their shell profile |

Any of them → say it out loud before going on:

```
⚠️ Гейт секретов на коммите не сработает: <.githooks/pre-commit нет или он не исполняемый | нет gitleaks | core.hooksPath не .githooks | в окружении SKIP_GITLEAKS=1>.
Остаётся проверка ниже и CI-скан, если он есть, — уже после push.
```

Do not switch the gate on yourself in this checkout: no `git checkout origin/main -- .githooks`, no copying or `chmod` of the hook, no `git config core.hooksPath`. The first two put files nobody asked for into this commit; the third rewrites the `.git/config` that every worktree shares. And never go around the gate: no `--no-verify`, no `-n`, no `SKIP_GITLEAKS=1`, no `-c core.hooksPath=…`.

**Scan what is staged** whenever `gitleaks` is installed, gate on or off — it takes a second. Keep the repo path at the end: without it gitleaks scans only the current directory's subtree and exits 0 for everything outside it.

```bash
top=$(git rev-parse --show-toplevel); out=$(gitleaks git --staged --redact --no-banner --no-color --log-level warn -v --exit-code 2 "$top" 2>&1); rc=$?; printf '%s\n' "$out"; printf '%s\n' "$out" | grep -qE '(^|[[:space:]])ERR[[:space:]]' && echo scan=FAILED; echo "rc=$rc"
```

- `rc=2` — a secret was found → the full stop below, whatever else the output says. Report its `RuleID`, `File`, `Line` and `Fingerprint`, never the value: `--redact` masks it (`Finding` and `Secret` read `REDACTED`), do not go looking for it.
- `rc=0` and no `scan=FAILED` — clean.
- `rc=0` with `scan=FAILED` — gitleaks printed an `ERR` line and still exited 0 (a wrong path or argument does this): the scan did not run. That is not «clean».
- any other code — the scan itself failed. Not «clean» either.

**Go on or stop:**
- gate on, scan clean → go on.
- gate off, scan clean → the scan stood in for the hook: give the warning above and go on.
- no `gitleaks`, or the scan failed → nothing real checks this commit before it reaches the remote. Give the warning, ask whether to commit with only the checks below, and commit only on an explicit «да» given after it. Quick mode does not skip this question.

Then the two checks below. Neither prints a value. Read the full `git diff --staged` only after both are clean: a diff with a secret in it puts the value into the chat.

**Check the list of staged files for dangerous names** (the list recorded above):
- `.env`, `.env.*`, `.env.local`, `.env.production`
- `*.pem`, `*.key`, `*.p12`, `*.pfx`

**Check the contents of staged files for dangerous patterns in string values** — `TOKEN`, `API_KEY`, `SECRET` or `PASSWORD`, then `=` and a quoted string of 8+ characters, or a `-----BEGIN … PRIVATE KEY-----` line. The command prints only `file:line`, never the line itself:

```bash
top=$(git rev-parse --show-toplevel); git diff --staged --name-only -z --diff-filter=ACMR | xargs -0 -r git -C "$top" grep --cached -n -I -E "(TOKEN|API_KEY|SECRET|PASSWORD)[[:space:]]*=[[:space:]]*[\"'][^\"']{8,}|-----BEGIN .* PRIVATE KEY-----" -- | cut -d: -f1,2
```

Empty output — clean. Do not open a reported line to see what matched: the `file:line` and the pattern's key name go into the stop below as they are.

**If found** — by the scan or by the checks above → FULL STOP. Show:
```
🚫 СТОП — обнаружены секреты в staged-файлах!

Файл: <путь к файлу>
Строка: <номер строки>
Что найдено: <RuleID из gitleaks или паттерн — без самого значения>
Отпечаток: <Fingerprint из gitleaks; у находки проверки по шаблону его нет>

Коммит заблокирован: пока проверка что-то находит, коммита не будет, даже по явной просьбе.
Что делать:
  1. Снять файл со staged: git restore --staged <файл>.
  2. Убрать значение из файла; секрет держать в .env или переменных окружения.
     Файлу, которому не место в git (.env, ключ), — строку в .gitignore; но файл,
     который git уже отслеживает, .gitignore не уберёт: это git rm --cached <файл>.
  3. Значение уже было в коммите или ушло в push — оно утекло, его нужно заменить.
  4. Срабатывание ложное — решать тебе. Находка gitleaks: комментарий gitleaks:allow
     в этой строке или отпечаток в .gitleaksignore. Находка проверки по шаблону:
     пометки для неё нет — коммит из своего терминала.
```
Do not continue while anything is found, even if the user asks. Whether a finding is false is the human's call. A gitleaks finding they call false may be marked (`gitleaks:allow` on the line, the `Fingerprint` in `.gitleaksignore`) only on their explicit word; the mark is part of the commit, so stage the file and `.gitleaksignore` again and run Step 1 from the start. A pattern-check finding has no mark: the human commits it from their own terminal. Never mark a line on your own to get past the stop.

---

### Step 2 — Building the commit message

Read `docs/4. <ПРЕФИКС>-guides/versioning_guidelines.md` (at RUNTIME, not from memory) — for the project's current Conventional Commits format.

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
1. Run `git diff --staged` (Step 1's checks are clean by now) and analyze the changes
2. Propose a commit message
3. Show it and wait for the user's confirmation

Either way, show the message together with the file list recorded in Step 1: the human confirms what goes in, not only the words.

Display format:
```
📝 Предлагаемое сообщение коммита:

  feat(tg-bot): добавить обработчик my_case для просмотра дела

Файлы в коммите (1):
  - tg_bot/handlers/menu/my_case.py

Подтверди ("ок", "да", "go") или скорректируй текст.
```

---

### Step 3 — Commit

After the message is confirmed, commit what Step 1 checked (the named files were staged there):

```bash
now=$(git diff --staged | sha256sum | cut -c1-16); if [ "$now" = "<сумма из шага 1>" ]; then git commit -m "<сообщение>"; else echo "index-changed: $now"; fi
```

`index-changed` → the index moved after the checks (another session, your own `git add`, a mark from the stop): nothing was committed. Run Step 1 again and show the new list before committing.

The permission rules match text, not intent: a Bash command containing `--no-verify`, a separate `-n`, `SKIP_GITLEAKS=`, `-c core.hooksPath`, `GIT_CONFIG_PARAMETERS` or `GIT_CONFIG_KEY_` is denied even when the string sits inside the quoted message — a `"$(cat <<'EOF' … EOF)"` message included. A message that has to name them goes into a file in the scratchpad (the Write tool), and the commit is `git commit -F <файл>`.

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

If the permission settings ask before every `git push`, the prompt is expected: it is the moment the human confirms the push. Declined → stop and report; do not retry through another form (`git -C`, an alias, a script). In a headless run (`claude -p`) nobody can answer, so an ask counts as a denial and the push is refused without a prompt. The commit then stays local: report «push не выполнен: нужен человек» with the branch and the commit hash, and stop.

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
Never force-push from the session. If the user explicitly asks for a force push — warn that it overwrites the remote history and give them the exact command to run in their own terminal (`git push --force-with-lease origin <ветка>`). The permission settings may deny it to the agent outright.

**C. Success:**
```
✅ Запушено!

Ветка:   <имя ветки>
Коммит:  <хеш> <сообщение>
Файлов:  <N> изменено
```

---

## Rules

- **Secrets are an absolute block for the agent**: a hit → stop; the agent never overrides it, even if the user insists. The human may mark a false gitleaks hit (Step 1) or commit from their own terminal
- **Read versioning_guidelines.md at runtime** — do not rely on memory for the commit format
- **Do not commit without confirmation** — always show the message before git commit
- **Never force-push from the session** — on an explicit request ("force push", "принудительно запушь") warn ("this will overwrite the remote history") and hand the human the exact command for their own terminal
- **Never bypass the commit-time gate** — no `--no-verify`, `-n`, `SKIP_GITLEAKS=1`, `-c core.hooksPath=…`; a gate that is off is said out loud (Step 1), not worked around and not switched back on by hand
- **A denied command is not respelled** — denied stays denied: no other spelling, alias, `git -C`, script or environment trick. If the denial hit text rather than an action, the text takes another route: a commit message through `git commit -F <файл>` (Step 3), a search through the Grep tool
- **The deny rules are a speed bump, not a guarantee** — they match only the canonical spellings that Claude Code types into Bash under this account; a script, Codex or another tool never meets them. What binds is this skill and the stop-lines
- **Do not add git add -A / git add .** without an explicit user instruction — only specific files
- **Staged without git add** — if the user did not specify files and there are already staged changes, use them

---

## Quick mode

If the user passed the commit message together with the command (for example: "запушь feat(tg-bot): добавить my_case") — you may skip waiting for message confirmation and commit immediately (after the secrets check). Show the summary after the push. Quick mode skips only that confirmation: when nothing real scans the commit (Step 1, «Go on or stop»), it still waits for the human's «да».
