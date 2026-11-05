---
name: close
description: >
  Closes the working session/day in one command — captures context (the project's
  canonical HANDOFF + agent memory + task statuses verified by fact), harvests repeated work into
  skills, prepares the day's commit with a secret scan, and sweeps temporary junk.
  Use when the user says "/close", "заверши сессию", "заверши день", "зафиксируй
  всё", "закрываемся", "конец дня". Paired with /intro, which restores the context
  next morning.
  If the project or the user has its own `close` skill, that one takes precedence — use this one only when the user typed `/team-skills:close` or no such skill exists.
---

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:close` and a skill named `close` exists in the project (`.claude/skills/close/SKILL.md`) or in the user's skills (`~/.claude/skills/close/SKILL.md`), stop: tell the user that their own `/close` takes precedence, and do nothing else.

## Project profile (mandatory)

After Step 0 and before any other action, read `.claude/team-skills.json` from the repository root. Require format `version: 1` and these keys: `handoff`, `changelog`, `docs.tasks`, `docs.specifications`, `docs.unsorted`. Read only the keys needed for this invocation. A missing file, unsupported version, or missing/empty required key means stop before reading or changing project documents: name the missing file/key and point to `team-skills:init_dev` and the catalog's `docs/team-skills-profile.md`. Never infer a prefix or substitute project paths.

In this skill, `{key}` means the value of that profile key; resolve paths relative to the repository root. These are notation, not literal shell variables: substitute and shell-quote the resolved values before executing commands. Paths must stay inside the repository.

Read `commands.push` if present; if the profile or that key is absent, the command defaults to `/team-skills:safe-push`. This command default never bypasses the mandatory document profile or authorizes a commit or push.

# /close — end the session: context, statuses, proposed commit, cleanup

The goal is to resume in a fresh session without losing verified context. Run phases in order and give one concise report at the end. The canonical current state lives at `{handoff}`; history belongs at `{changelog}`. Task closure is handled by `/accept`, not duplicated here.

## Phase 0 — Skip empty sessions

Did the session produce durable decisions, changes, artifacts, rules, or findings?
If not, report "Nothing to record" and name any open thread, then stop.
Otherwise collect what was done (IDs/paths), the owner's decisions and reasons,
remaining work and next step, verified pitfalls, and unfinished risky actions.
Do not invent evidence. Use this summary in every phase below.

## Phase 1 — Harvest repeated work

1. Work repeated at least twice is a candidate for a skill or script. List repeated code, routines, and pitfalls.
2. Check existing project skills and scripts if the project has them. Extend existing mechanisms instead of duplicating them.
3. Record candidates in the project's documented candidate registry or backlog. If no such location is documented, list candidates in the report and ask where to record them; do not invent a path. Rank by frequency × cost × longevity. Build the top candidate only with the owner's approval.
4. Register what was built in the project's existing skill registry and mark the candidate as built.
5. If the project has a skill exchange script such as `scripts/skill_sync.sh`, mention its documented sharing procedure. Do not execute its push operation without explicit approval for the concrete files and action in this chat.

## Phase 2 — Context and factual task statuses

1. Review session-related open tasks under `{docs.tasks}` and task tables in `{docs.specifications}`:
   - Progressed: keep 🟡 and update the progress comment.
   - Completed AND verified by an artifact or actual test output: suggest `/accept T<NN>` for the move to Done and updates to history/current state.
   - Waiting: state exactly what is missing. Unverified completion stays 🟡 and gets a separate report line.
2. Update the current-state section of `{handoff}` without appending a history log:
   - Put a 2–4 line resume prompt in the existing RESUME-PROMPT section, or at the top of the current-state section if none exists. State the work, current point, and next action. `/intro` reads it there.
   - Include unfinished risks, verified results and paths, remaining work, pitfalls, blockers, and git state (branch and uncommitted changes).
3. Update only the current project's agent memory, using its established memory location and format. Store 2–5 durable facts not already recoverable from repository files or git. Extend an existing topic instead of duplicating it, and maintain the memory index. Never use another project's memory path.
4. Record ideas or deferred specs in the project's documented backlog. If no location is documented, include them in the report instead.

If the project has parallel session tooling such as `scripts/ops/session.sh`, serialize shared state and memory writes using an atomic `mkdir .close-lock` lock and release it with `rmdir` after writing. For one session, skip the lock.

## Phase 3 — Executor effectiveness

If the project documents executor tiers and delegation rules, follow those rules.
Record delegated code changes, direct changes with their authorized exceptions,
and brief mismatches with concrete evidence. Do not impose another project's
executor hierarchy. Give 1–2 actionable recommendations and record them in the
project's documented registry/backlog/runbook, or flag the missing destination
in the report. If no tiers are defined, skip this phase and say so.

## Phase 4 — Proposed commit, cleanup, report

1. Scan the changed files for secrets without exposing their values: JWT-like strings, private-key headers, bearer tokens, passwords, client secrets, and access tokens. Report only locations. Do not include secret files in the proposed commit. Check new files with `git check-ignore -v <file>`; report an ignored source file instead of silently forcing it into git.
2. **Prepare a commit; do not authorize it yourself.** Show the exact file list and proposed Conventional Commit message. Commit, push, merge, PR creation/merge, branch deletion, and worktree deletion each require an explicit human "yes" in this chat for that concrete file list and action. A request to commit does not authorize push. Flags such as `--yes`, cron, configuration/HANDOFF permissions, and plan approval through a notification button do not count.
   Use `{commands.push}` (default `/team-skills:safe-push`) only after approval for the specific action; pass through its limits. If only commit was approved, require the command to stop after commit; if it cannot, do not invoke it and report the limitation. Ask separately before push.
   Without a human in chat, stop at **ready to commit** with the file list and proposed message; send a notification only if a channel is configured and authorized.
3. Cleanup is idempotent, bounded, and based on inspected files:
   - Regenerable session artifacts may be removed after checking they are disposable and unused: browser snapshots, ignored Python caches, session scratchpads, temporary quality-run results, and `/tmp/sup-codex/` worker artifacts older than seven days. Keep fresh worker results and files owned by live tasks. Report count and reclaimed size.
   - Show meaningful root files, untracked directories, and testing artifacts under `{docs.unsorted}` for the owner's decision.
   - Never remove secrets, project memory, source or documentation without explicit approval, other sessions' worktrees, or agent configuration directories. Branch/worktree deletion always needs the separate approval above. When uncertain, list it instead of deleting it.
4. Report in one screen: harvested candidates/built skills; context and statuses (ready for `/accept`, unverified items, next step, return via `/intro`); executor summary or skipped phase; commit proposal/approved action and actual hash; cleanup counts and items awaiting a decision.

## Guardrails

- Close statuses only against verified facts; complete task closure goes through `/accept`.
- State unfinished and unverified work plainly.
- Never expose secret values.
- Do not change production systems, deploy, or migrate during `/close`.
- Keep each recommendation in an established home or explicitly report that its destination is unresolved.
