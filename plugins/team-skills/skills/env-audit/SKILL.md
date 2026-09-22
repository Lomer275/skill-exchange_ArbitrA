---
name: env-audit
description: Audits and repairs a person's working setup: a collector gathers the facts (rules and memory, skills, secrets and 1Password, network reach, token spend, documentation, project architecture), the agent interprets them, allowed repairs are applied only after an explicit yes, and a sandbox run proves that closing the day writes where the skills claim. Use when the user says "/env-audit", "проведи аудит окружения", "проверь моё окружение", "прими рабочее место", "почему агент выдумывает", "агент не помнит", "audit my setup", or hands over the audit brief to run.
---

# /env-audit — accept a working setup: measure, then fix what is allowed

Read **`audit-brief.md`** (Russian, under 20 KB) before touching anything: it is the
authority on how to run. This file says what the pieces are and what may never happen.

## Tools

| Command | What it does | Writes anything? |
|---|---|---|
| `python3 collect.py --output ~/audit-<date>/facts.json` | gathers every fact into one JSON: machine, instructions, handoff, skills, tokens, Codex config and memory, 1Password, network, secrets, regulations, architecture | only the output file |
| `python3 collect.py --scan-file <file>` | checks a file you are about to show or save for secret values; exit code 3 means something matched | no |
| `python3 collect.py --bundle \| ssh host python3 - --expect-user <name> …` | runs the collector on another machine of the same person without writing anything there | no |
| `python3 cleanup.py plan / render / apply --confirmed / verify / rollback --confirmed` | produces a concrete diff of the allowed repairs, applies it after the person says yes, backs every file up, can undo | only after `--confirmed` |
| `python3 reality_check.py estimate / prepare / command / run --confirmed / verdict / cleanup` | proves in an isolated sandbox whether `/close` and `/accept` really write to the canonical HANDOFF and CHANGELOG | inside the sandbox only |

The collector needs python3.10 and the standard library — nothing else. Exit codes:
0 done, 2 no project root found, 3 the self-check redacted a value, 4 wrong account,
5 not a POSIX system — on native Windows follow `references/windows.md` (`--scan-file` still works).

## Before step 0 — make sure this is v3

`collect.py` and `meta.json` with version 3.x must lie next to this file. If they do not,
or the brief you loaded calls itself v2.x, the person is running a stale copy: stop and say so.
The usual cause is updating the marketplace folder with `git pull`. That refreshes the
catalogue but not the installed plugin. The fix: `/plugin marketplace update skill-exchange`,
update `team-skills` in `/plugin`, then reload the editor window. In VS Code a new chat in the
same window keeps the old skill list.

## The run, in nine steps

0. **Consent #1** — one message listing the read-only actions, then one yes for the run.
1. `collect.py` → `facts.json`. No model calls, no changes.
2. Interpret the facts and run the critical pass over your own findings.
3. Interview the person (`references/interview.md`).
4. Build the plan: whitelist items plus the cleanup diff.
5. **Consent #2** — show `plan.diff` in full, then `cleanup.py apply --confirmed`.
6. **Consent #3** — show the cost estimate, then the sandbox run.
7. `collect.py --scan-file` over the report, the chat summary, the evidence and every diff.
8. Deliver `REPORT.md`, `facts.json`, a 10–15 line chat summary and an instruction list.

The order is strict: a repair made before the snapshot destroys the "before" picture.

## Hard rules

- **Measure first, fix second.** Never the other way round.
- **Never print secret values** — anywhere. Counts and key names only. A value that leaked
  into output is never repeated; it is marked "requires rotation".
- **Never log in over ssh to production or to anyone else's machine.** Reachability is
  judged from local data only.
- **The whitelist is closed.** Only `cleanup.py apply` and the items in
  `references/whitelist.md`. Deleting files, moving them, rewriting git history, rotating
  secrets, committing, pushing, creating anything on GitHub, messaging people — all of
  that goes into the instruction list for the person, never into your hands.
- **A claim without command output is a hypothesis, not a finding.** Sections marked
  `truncated`, `skipped` or `positive_control: fail` are never reported as clean.
- **Name your blind spots**, and label numbers from partial data as lower bounds.
- One agent run in the sandbox is the only exception to "do not spawn agents", and only
  after consent #3 with the cost shown.

## Reference modules — read on demand, not upfront

`architecture.md` · `secrets.md` · `machine.md` · `process.md` · `whitelist.md` ·
`interview.md` · `tokens.md` · `network.md` · `onepassword.md` · `cleanup.md` ·
`reality.md` · `windows.md` · `traps.md` (read this one **before** you start).

## Codex profile

If the person works on Codex, the skill-exchange, the ten mandatory skills and the
superpowers plugin are marked "not applicable", not "violated"; memory lives in
`$CODEX_HOME/memories`; `approval_policy` and `sandbox_mode` are the Codex equivalent
of the whitelist; skill cleanup and the sandbox check do not apply.

The report, the summary and the reference modules are in Russian.
