---
name: impl
description: >
  Delegates writing code to a Codex implementer for ANY change — no TNN task file
  required. Claude does the thinking (locates the code, decides the approach, writes
  a precise brief), Codex writes the code, Claude reviews the resulting diff and runs
  the tests. Use when the user says "/impl", "реализуй", "напиши код",
  "сделай правку", "поправь", "внеси изменение", "добавь фичу", "перепиши",
  or whenever a change to executable code (*.py, tests/, *.sql, *.sh, *.js) is needed
  outside of /sprint-codex (which is spec-driven) and /fix (which consumes review findings).
  Part of spec S11 — the Claude × Codex division of labour.
  If the project or the user has its own `impl` skill, that one takes precedence — use this one only when the user typed `/team-skills:impl` or no such skill exists.
---

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:impl` and a skill named `impl` exists in the project (`.claude/skills/impl/SKILL.md`) or in the user's skills (`~/.claude/skills/impl/SKILL.md`), stop: tell the user that their own `/impl` takes precedence, and do nothing else.

## Codex model and effort (mandatory)

Resolve each value independently: explicit invocation argument (`model=`, `effort=`) →
`.claude/codex.json` → built-in `gpt-6-luna` / `medium`. Never use
`~/.codex/config.toml` for model selection. Pass both resolved values on every
worker call and model launch; probes, warm-up and smoke tests use the resolved
model with effort `low`. Cache availability by model, probe effort and engine (TTL 1h);
a different model requires a fresh probe. Log/report the model and effort actually sent.

Luna: `gpt-6-luna`, effort `low|medium|high|xhigh|max` (no `ultra`).
Sol: `gpt-6.1-sol`; Astra: `gpt-6-astra` (most expensive).
A caller choosing a stronger model must explain why in one line to the user.
Reject unsupported model/effort combinations; never silently drop or lower effort.

## Project paths

No project profile is required. If `.claude/team-skills.json` exists, read only needed keys `handoff`, `changelog`, `docs.tasks_done`, `docs.guides`, `docs.business_requirements`.
Missing profile/key → skip that project-document step and report it; never guess a prefix or use project-specific fallback paths.
All document paths are repository-relative. Resolve GUIDES_DIR from `docs.guides`; protect only configured `handoff`, `changelog` and `docs.tasks_done` paths.

Resolve the push skill from `commands.push` in `.claude/team-skills.json`; if the file/key is absent use `/team-skills:safe-push` (the only command default). References to `<push-command>` below mean this resolved command.

# /impl — Claude decides, Codex implements

The generic delegation path. `/sprint-codex` covers spec-driven waves, `/fix` covers
review findings — **`/impl` covers everything else**: an ad-hoc change, a new function,
a refactor, a bug fix found in conversation.

**The division of labour is the whole point.** Claude must not hand Codex a raw user
sentence and call it delegation — that produces a worker that guesses the design.
Claude does the thinking; Codex only types.

| Stage | Owner | Output |
|---|---|---|
| Understand the request, locate the code, pick the approach | **Claude** | a brief |
| Write the code | **Codex** | a diff |
| Review the diff, run the tests, decide "good / redo" | **Claude** | a verdict |

---

## Input

- `/impl <что нужно сделать>` — free-form description.
- `/impl` with no argument → use the task from the current conversation. If unclear, ask **one** clarifying question.
- `--files a.py,b.py` — optional explicit scope override (otherwise Claude derives it in Step 1).
- `--self` — after enabled routing checks, an explicit user override: Claude implements it directly (skips delegation). Announce, do Step 1 items 1–3 (the business/legal check in item 3 included), take the before-snapshot from Step 3, implement, then review it as Step 4 «Своя правка» says.

---

## Algorithm

### Step 0 — Routing checks

1. Require an existing, valid `.claude/codex.json` with `enabled=true`.
   Missing/false → STOP and suggest `/team-skills:codex-setup`.
   A false `SUP_CODEX_ENABLED` override also stops; env true never bypasses the file requirement.
2. Resolve model and effort as above. For stale/unmatched availability cache, probe:
   `timeout 30 codex exec -m "$MODEL" -c model_reasoning_effort=low --skip-git-repo-check "ok" < /dev/null`.
3. Check CLI version with `codex --version`. Unavailable → STOP with the setup hint.

---

### Step 1 — Claude thinks (mandatory, do not skip)

This is the step that makes the delegation worth anything. Before writing the brief:

1. **Locate the code.** `Grep`/`Glob`/`Read` the relevant files. Never delegate against a guessed path.
2. **Understand the surroundings.** Read the module's `CLAUDE.md` (for example `src/app/` or `src/shared/`) — it holds the module's patterns and pitfalls.
3. **Decide the approach.** Where the change goes, which existing helper to reuse, what must NOT be touched, what the edge cases are. If two approaches are genuinely open and the choice is the user's, ask *before* delegating — never hand ambiguity to Codex.
   Business and legal constraints (domain rules, texts the user sees, money, deadlines) cannot be derived from the code. If the brief depends on one, look in the spec and the task file first, then in the business requirements if the project keeps them; their silence is not an answer. Not found, and a wrong value could reach a user's text, money or a legal deadline — or you cannot tell whether it could → ask the owner before delegating. Only a reversible internal choice (a log level, a retry count, a helper's name) goes into КОНТЕКСТ as an explicit assumption («Допущение: …») so the reviewer and the owner can see it; Step 5 repeats it.
4. **Fix the scope.** The exact list of files Codex may edit. This becomes `scope=edit:<paths>`.
5. **Define the DoD.** How we will know it works: which test, which command, which observable behaviour.

If Step 1 reveals the change is a one-liner in a file already open in this session
(≤ 3 lines, obvious, zero design content) → this is the exceptions pocket:
announce «Делаю сам — правка N строк, брифовать дороже», take the before-snapshot from Step 3
and edit directly. Then review it as Step 4 «Своя правка» says.

---

### Step 2 — Write the brief

`Write` it to `~/sup-codex/impl-<slug>-brief.md` (`mkdir -p ~/sup-codex` first), where
`<slug>` is a short kebab-case name of the change (e.g. `voice-rate-limit`).
**Not `/tmp`:** some hosts wipe `/tmp` every night, and the brief is evidence the evidence
package and later reviews read. Template — all eleven sections are required:

```markdown
# ЗАДАЧА
<одно предложение: что должно измениться в поведении системы>

# КОНТЕКСТ
<почему; какой баг/фича; что уже выяснил Claude — путь, виновная строка, механизм>
Модуль: <project module path> — читай его CLAUDE.md.

# ЧТО СДЕЛАТЬ
1. <шаг с указанием файла и функции>
2. <...>

# ГРАНИЦЫ
Правь только файлы из раздела ФАЙЛЫ.
НЕ трогай: <рефакторинг вне задачи; переименования; конкретные соседние файлы, если есть соблазн>

# КРАЙНИЕ СЛУЧАИ
- <что должно произойти при пустом значении / ошибке сети / выключенном флаге>

# ПРИМЕРЫ
- Дано <состояние>; когда <действие>; тогда <наблюдаемый результат>.
- Дано <...>; когда <...>; тогда <...>.
<не меньше двух; каждый — готовый тест: Codex превращает их в тесты>

# ФАЙЛЫ
- `path/to/file.py`
- `tests/unit/test_file.py` — новый
<по пункту на путь или маску от корня репозитория; всё после « — » или « # » — комментарий;
маска через fnmatch, `*` совпадает и с `/`. Это и есть скоуп: гейт режет всё, что вне списка>

# ПЕРЕИСПОЛЬЗОВАТЬ
- `module.py:function` — <зачем>
<что уже есть и чего не писать заново; если нечего — так и написать: «нечего, новый модуль»>

# ВНЕ СКОУПА
- <что соблазнительно сделать попутно, но нельзя>

# БЮДЖЕТ
<час | полдня | день> — <если за бюджет не уложился, остановись и опиши, что мешает>

# DoD
- <проверяемый критерий: тест X зелёный / команда Y печатает Z>
- Существующие тесты не сломаны.
```

**Format rules the checker enforces** (`scripts/staff/brief.py`): a section starts with a
level 1–3 Markdown heading; order and case are free; a section holding only blank lines and
`<…>` placeholders counts as empty; `ПРИМЕРЫ` needs ≥2 top-level bullets, each with
«дано», «когда», «тогда»; `ФАЙЛЫ` needs ≥1 path; `БЮДЖЕТ` starts with `час`, `полдня` or `день`.

**Quality bar for the brief:** a competent engineer who has never seen this
conversation must be able to implement it without asking a question. If your brief
fails that bar, you skipped Step 1.

---

### Step 3 — Delegate

**Check the brief first** — if `scripts/staff/brief.py` is present, from the repo root (or the worktree Codex will work in):

```bash
python3 scripts/staff/brief.py check ~/sup-codex/impl-<slug>-brief.md
```

- Exit `0` → go on.
- Exit `1` → the brief has an empty or malformed section; the output names it. Fill it in
  and re-run. **Do not call `codex-worker`** until the check is green — a brief with a hole
  is exactly the brief that makes Codex guess.
- `scripts/staff/brief.py` absent (not in this project or branch) → say so in one line
  («brief.py нет в этой ветке — проверил поля по шаблону глазами») and check the eleven
  sections by eye against the template above.

Build `scope=edit:` from the brief's `ФАЙЛЫ`, not from memory. If present, use
`python3 scripts/staff/brief.py files ~/sup-codex/impl-<slug>-brief.md | paste -sd,`; otherwise extract the listed paths manually, preserving masks and removing comments.

**Snapshot the tree before the worker starts.** The checkout is often dirty with other
sessions' work, and then `git diff` after the worker mixes its lines with theirs. Record the
working tree, untracked files included, as a tree object built in a throwaway index:

```bash
mkdir -p ~/sup-codex
GIT_INDEX_FILE=$HOME/sup-codex/impl-<slug>.idx git -C <repo> read-tree HEAD && GIT_INDEX_FILE=$HOME/sup-codex/impl-<slug>.idx git -C <repo> add -A && GIT_INDEX_FILE=$HOME/sup-codex/impl-<slug>.idx git -C <repo> write-tree > ~/sup-codex/impl-<slug>-before.tree
```

`<repo>` — the worktree Codex works in, else the repo root. The same command with
`-after.tree` runs when the worker returns (Step 4). On a corrective round keep the first
`-before.tree`: the diff then covers both rounds.
- `git add -A` here writes only the throwaway index. The real index is untouched.
- Write the index path out in each of the three commands; never put it in a variable of
  your own. An empty `GIT_INDEX_FILE` silently means the real index. No `sh -c`, no `rm`:
  the next `read-tree` resets the `.idx` file.
- Ignored files are not in the tree. `.claude/` is ignored: a change there is read file by file.

Call the worker via the Skill tool:

```
Skill(skill="codex-worker", args="role=implementer model=<resolved-model> effort=<resolved-effort> brief_file=$HOME/sup-codex/impl-<slug>-brief.md scope=edit:<paths from ФАЙЛЫ> task_id=impl-<slug> timeout_min=15")
```

Pass the brief path expanded (`/home/<user>/sup-codex/...`), not with `~` — the worker
checks the file's existence literally.

- `worktree` — omit (defaults to `current`). Pass a worktree path only when the caller is already isolated.
- Pass resolved `model=` and `effort=` explicitly. A stronger model requires a one-line explanation to the user.
- **Parallel changes.** If Step 1 decomposed the request into ≥2 changes with **no shared files**, write one brief each and call `codex-worker` N times in a single message. Overlapping files → sequential, no exceptions (concurrent workers on one file clobber each other).

Announce the delegation in one line: «Отдаю Codex: <что>. Скоуп: <файлы>».

---

### Step 4 — Claude reviews (mandatory)

Codex returning `status: ok` is not evidence the change is right. When the worker returns,
take the after-snapshot first: the Step 3 command with `-after.tree`. Below, `<before>` and
`<after>` are the two tree ids (`$(cat ~/sup-codex/impl-<slug>-before.tree)` and the same for
`-after.tree`). After any edit of your own (a blocker fixed directly, a pocket edit), take the
after-snapshot again before re-running items 1–4 or writing the item 6 patch: the old one
does not hold your fix.

**Своя правка** (`--self`, the ≤3-line pocket, Claude finishing after a
second miss or a timeout): the same items, with three differences. Item 0 runs only if a brief
exists. Item 2 checks against the brief, or the user's request when there is none. A blocker
you find is fixed directly, then items 1–4 run again — no `# ПРАВКИ ПО РЕВЬЮ`, no
re-delegation. Item 6 applies once the task's pocket lines total more than 3.

0. **Scope gate first** — if `scripts/staff/scope_check.py` is present, before reading a single line of the diff:
   ```bash
   python3 scripts/staff/scope_check.py --brief ~/sup-codex/impl-<slug>-brief.md \
     --repo <worktree or repo root> --base origin/main --format text --task <KEY> \
     > ~/sup-codex/impl-<slug>-scope.txt; echo "exit=$?"; cat ~/sup-codex/impl-<slug>-scope.txt
   ```
   `<KEY>` — the tracker's task number, else `impl-<slug>`. `--base` — the branch the work started from
   (`origin/main` by default; a sprint branch when working inside one). The `-scope.txt` file stays
   next to the brief: the evidence package picks it up.
   - Exit `0` (GREEN) → go on to item 1. `owner_review:` lines are not a failure, but name them in the report: those paths need the owner's eyes.
   - The gate diffs the whole tree from `--base`, so on a tree dirty outside the change its `outside_brief` list also holds files the worker never touched. Check each listed path against `git -C <repo> diff-tree -r --name-status <before> <after>`: a path missing from it was dirty before the worker started — name it in the report, it is not a RED. Only paths the snapshot diff shows count below.
   - Exit `1` (RED: `outside_brief`, `test_tampering`, `lint`, `lint_unavailable`) → **no review**. Append `# ПРАВКИ ПО РЕВЬЮ` with the gate output to the brief and re-delegate — this *is* the one corrective round from item 5. Exception: `lint_unavailable` is our environment, not Codex's miss — install ruff (`/usr/bin/python3 -m pip install --user ruff`, lands in `~/.local/bin/ruff`) and re-run the gate; never skip it.
   - Exit `2` → the brief or the environment is broken (no `ФАЙЛЫ`, bad `--base`, not a git repo). Fix that; do not call Codex.
   - The change touches only `.claude/` (not in git) → the gate does not apply; say so in one line.
   - `scripts/staff/scope_check.py` absent (not in this project or branch) → say so in one line, compare the union of `git diff --name-only` and `git ls-files --others --exclude-standard` against the allowed paths in `ФАЙЛЫ`. An extra file → STOP and show its path; do not silently ignore it.

1. **Read the diff.** `git -C <repo> diff-tree -r --name-status <before> <after>` lists what the worker changed, new files included; `git -C <repo> diff <before> <after>` is its diff, without the lines that were dirty before it started. Actually read it, not just the worker's summary. A change under `.claude/` is not in the tree — read the files.
2. **Check against the brief:** does it do what was asked, and *only* that? Flag scope creep (untouched-file edits, drive-by renames, gratuitous refactoring).
   **No fake completion — a blocker, not a nit.** In the added lines look for `pytest.skip` / `@pytest.mark.skip` / `skipif` / `xfail`, `raise NotImplementedError`, a body of only `pass` or `...` next to a TODO, `assert True` or a test with no real assertion — unless the brief asked for it (an abstract method of a base class is the normal pattern). An empty diff reported as `ok` counts too: `<before>` and `<after>` are the same id. The one exception — the behaviour is already on the work's base (item 0's `--base`, `origin/main` by default): show it with `git show <base>:<path>`, run the DoD on the unchanged tree, and if it passes, tell the user the brief rested on a wrong premise and stop — no corrective round. Any of these → the change is not done: quote the line in `# ПРАВКИ ПО РЕВЬЮ` and use the corrective round from item 5. The scope gate does not catch them: it flags only modified or deleted tests outside `ФАЙЛЫ`, runs ruff with `F,E9` only, and an empty diff is GREEN.
3. **Check the pitfalls** the module's `CLAUDE.md` warns about.
4. **Run the tests:** use the task DoD and the current project's CLAUDE.md/CI commands and runtime. Do not invent project-specific commands, environment values or database settings. For pytest, use `-rsx` to show skipped/xfail results: a newly skipped reproduction is item 2's blocker. A setup failure before tests run proves nothing; diagnose it using the project's documented environment and report any unresolved limitation with the actual output.
5. **Verdict:**
   - Clean → Step 5 (item 6 first if the task's pocket lines total more than 3).
   - Small deviation → **one** corrective round: append a `# ПРАВКИ ПО РЕВЬЮ` section to the brief and re-delegate (Step 3). A red scope gate in item 0 already used this round.
   - **Second failure on the same change** → exceptions pocket: Claude finishes it directly, announcing «Codex дважды промахнулся — доделываю сам». Do not loop.
   - Worker `status: timeout|error` → read `/tmp/sup-codex/<task_id>-implementer.err`, one retry with a longer timeout, then take over.
6. **Code Claude typed itself gets a fresh reviewer.** If the pocket cases of this task left Claude typing more than 3 lines in total over the task's diff (see Rules), items 1–4 are the author reviewing their own diff. Before Step 5, get a review with fresh context:
   - The change is task T<NN>'s and Codex is up → `/codereview-dual T<NN>`; it reads the task's files itself. If its table carries the `[fallback: claude-only …]` marker, the review was Claude's own after all: run the subagent review below as well.
   - Otherwise → write the change to a patch, `git -C <repo> diff <before> <after> > ~/sup-codex/impl-<slug>.patch` (the working tree, not commits, so a SHA range would show nothing; new files are in it). Give it to a subagent with `model: "sonnet"` (`subagent_type: "general-purpose"`), told to read `.claude/skills/codereview/SKILL.md` and review the patch file against the brief (or the user's request, when there is no brief). Not `superpowers:requesting-code-review`: it reviews a SHA range.
   - **What the verdict changes.** CRITICAL/HIGH → fix them and run items 1–4 again. One more fresh review only if that fix is itself more than 3 lines, and that one is the last. CRITICAL/HIGH still open after it, and every MEDIUM/LOW, go to «Риски / follow-ups» in Step 5.
   - In the report: the reviewer, its «Найдено: …» line, and what was fixed.

---

### Step 5 — Report

One screen:

- **Что изменено** — files with line counts, one line of intent each.
- **Тесты** — the command and its actual result (paste the tail; never claim green without output).
- **Ревью** — who reviewed the diff: you (Codex wrote it), or the fresh reviewer from Step 4 item 6, its «Найдено: …» line and what was fixed.
- **Допущения** — every «Допущение: …» from the brief, and any assumption you made on a route without a brief, so the owner can confirm or correct it.
- **Риски / follow-ups** — anything the change leaves open.
- **Не закоммичено** — state it plainly.

**Never commit or push.** Commits happen only on the user's explicit request (`<push-command>`).

---

## Rules

- **Claude does not write executable code by default.** `*.py`, `tests/`, `*.sql`, `*.sh`, `*.js` are Codex's. Docs (`*.md`), specs, task files, configs (`*.yml`, compose, workflows) and agent memory stay with Claude — that is the "thinks and decides" half.
- **The exceptions pocket is narrow and must be announced out loud:** a timeout/error takeover after enabled routing · ≤3-line obvious edit in an already-open file · second Codex miss on the same change · the change requires live dialogue with the user mid-edit · `--self`.
- **More than 3 lines typed by Claude go through Step 4 item 6** — counted in total over the task's diff, all pocket cases together: three 2-line pocket edits are 6 lines.
- **Never delegate a brief you could not implement yourself.** If you cannot specify it, you have not understood it — go back to Step 1.
- **Never trust `touchedFiles`** from the companion engine — determine the changed files via `git`.
- Codex does not commit, does not touch `.env*`, `<profile:changelog>`, `<profile:handoff>` or `<profile:docs.tasks_done>/` — enforced by `AGENTS.md`, restated in the brief when the scope is near them.

---

## Related

- `<profile:docs.guides>/runbook_codex_routing.md` (only if configured and present) — the routing matrix and the division-of-labour law.
- `/sprint-codex` — the same delegation, but spec-driven with waves and worktrees.
- `/fix` — applies findings from `/codereview*` (delegates to Codex the same way).
- `/codereview-dual` — Codex as reviewer, not implementer.
