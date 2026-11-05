---
name: intro
description: >
  Loads the project context at the start of a session — the paired opener for /close.
  Reads the project's canonical HANDOFF (the «Продолжаем…» line at the top), the open tasks and the current branch state,
  then reports where we stopped, the next step and the open blockers. Use when the user
  says "/intro", "продолжаем", "что у нас", "с чего начинаем", "загрузи контекст",
  "что вчера делали".
  If the project or the user has its own `intro` skill, that one takes precedence — use this one only when the user typed `/team-skills:intro` or no such skill exists.
---

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:intro` and a skill named `intro` exists in the project (`.claude/skills/intro/SKILL.md`) or in the user's skills (`~/.claude/skills/intro/SKILL.md`), stop: tell the user that their own `/intro` takes precedence, and do nothing else.

## Project profile (mandatory)

After Step 0 and before any other action, read `.claude/team-skills.json` from the repository root. Require format `version: 1` and these keys: `handoff`, `changelog`, `docs.tasks`. Read only the keys needed for this invocation. A missing file, unsupported version, or missing/empty required key means stop before reading or changing project documents: name the missing file/key and point to `team-skills:init_dev` and the catalog's `docs/team-skills-profile.md`. Never infer a prefix or substitute project paths.

In this skill, `{key}` means the value of that profile key; resolve paths relative to the repository root. These are notation, not literal shell variables: substitute and shell-quote the resolved values before executing commands. Paths must stay inside the repository.

# /intro — restore session context

The read-only opener paired with `/close`. Read silently and report one screen.

## Read in order

1. `{handoff}`: read the resume prompt in RESUME-PROMPT, or the first lines of the current-state section where `/close` left it. Include unfinished risks, blockers, and recorded git state.
2. `{changelog}`: read the unreleased section for completed work not yet released.
3. `{docs.tasks}`: find open 🟡 tasks and their linked specifications.
4. Git: run `git status --short`, `git log --oneline -5`, and determine the current branch. Report discrepancies with the handoff, including unrecorded changes or a different branch.
5. If the project documents a skill-candidate registry, read it if present. Do not invent its location.

## Output

Report: where we stopped (1–2 lines from the resume prompt), the concrete next
step, open blockers (or none), and repository state (branch, uncommitted file
count, and any discrepancy). Finish with "Ready to work."

## Rules

- Change nothing: no edits, commits, or deploys.
- If the handoff predates recent commits, report how far it lags and that its content may be stale.
- If the configured handoff file is absent or empty, reconstruct context from git history and configured open tasks and label it indirect evidence. This does not permit proceeding without the required profile key.
- Do not retell the entire project instructions.
