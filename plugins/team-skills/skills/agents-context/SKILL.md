---
name: agents-context
description: Sets up shared context for both AI agents (Claude Code and Codex) in a project — team policy in the global slots, a project AGENTS.md, and a filled-in project description. Use when the user says "/agents-context", "настрой контекст агентов", "обогати контекст", "подключи проект к общим правилам", "у codex нет контекста", "настрой agents.md", "поставь общие правила", or when opening a project whose AGENTS.md is missing or still holds the unfilled template.
---

# /agents-context — both agents learn the same rules

A thin wrapper. **The script does the mechanics; you do the one thing it cannot** —
look at the repository and describe it.

Do not reimplement what the script does. If it fails, report and stop.

---

## Why a script and not just you

The moment somebody most needs this is the moment their Claude limit ran out and
they are moving over to Codex. A setup path that needs a model fails exactly then.
So the mechanics are deterministic and free:

```bash
scripts/ops/agents-context/agents-context.sh apply --project .
```

That command alone gives working context. Everything below only adds the project
description on top. **Tell the user this** if they are near a limit.

---

## Steps

### 1. Run the script

```bash
<skill-dir>/agents-context.sh apply --project .
```

Read its report. It says exactly what it wrote and what it skipped, and why.

- Non-zero exit → show the message and **stop**. Corrupted markers are the usual
  cause, and they are a person's job to untangle, not yours.
- `Codex не найден` / `Claude не найден` is not an error — that agent is not
  installed here. Say so and continue.

### 2. Understand the project

Read enough to describe it honestly. Usually: `README`, the manifest
(`pyproject.toml`, `package.json`, `go.mod`, …), the entry point, the test
configuration, `.github/workflows/`, `docker-compose*.yml`.

Answer four questions:

- **What is it** — one or two sentences a newcomer would understand.
- **Stack and entry point** — language, framework, what starts it.
- **How tests run** — the actual command, verified against the config, not guessed.
- **Where it is deployed** — or "nowhere, local only", which is also an answer.

### 3. Fill the scaffold — outside the block only

The script leaves `<!-- Заполни: … -->` placeholders in `AGENTS.md`, **outside**
the managed block. Replace them with what you found.

**Never write inside `<!-- BEGIN team-context -->` … `<!-- END team-context -->`.**
That region is regenerated on every run; anything you put there is lost. It is
also the same text on every machine in the team — editing it locally would make
one person's rules diverge from everyone else's.

If `CLAUDE.md` was created as a scaffold too (it only is when the project had
none), fill it the same way. If the project already had a `CLAUDE.md`, leave it
alone — the script did not touch it and neither should you.

### 4. Report

Short. What the script wrote, what you filled in, and what is still open —
typically project bans and secrets, which only a person can state.

---

## Rules

- The block is the script's territory; the text around it is yours.
- Do not invent facts about the project. "Tests: not configured" beats a plausible
  command that does not exist.
- Do not touch `.env*`, `.servers` or anything holding secret values. If the
  project needs them, name the variables, never their contents.
- Do not commit. Show the result and let the person decide.

## Related

- `policy.md` next to this file — the team policy text that lands in the global
  slots. Editing it changes the rules for everyone; that is a deliberate act.
- `agents-context.sh check --all` — find drift without changing anything.
- `agents-context.sh link-worktrees` — give existing worktrees the project's skills.
