---
name: env-audit
description: Audits and provisions a person's whole working setup against eleven team requirements — skill exchange, mandatory skills, project documentation layout, GitHub wiring, the three levels of Claude rules and memory, the Claude×Codex pairing, Docker, Bitrix task regulations, working principles, a user profile, and the superpowers plugin. Snapshots everything first, then fixes only what is on a closed whitelist, then reports. Use when the user says "/env-audit", "проведи аудит окружения", "проверь моё окружение", "прими рабочее место", "почему агент выдумывает", "агент не помнит", "audit my setup", "настрой моё окружение по стандарту", or hands over the audit brief to run.
---

# /env-audit — accept a working setup: measure, then fix what is allowed

The full brief lives in **`audit-brief.md`** next to this file. It is written in Russian,
addressed to you, and it is the authority: follow it step by step rather than improvising.

## How to run

1. Read `audit-brief.md` completely before touching anything. Section 0 defines the role
   and the whitelist, section 1 the protocol, **section 2.0 the eleven mandatory
   requirements**, sections 3–7 and phases F–G the snapshot, phase H the allowed fixes,
   section 9 the traps that make audits produce confident wrong answers.
2. **Take the whole snapshot before changing anything.** A fix made before the measurement
   destroys the "before" picture and invalidates the run.
3. Only then run phase H, and only what its whitelist names. Everything else — deletions,
   moves, rewrites, anything leaving the machine — goes into the plan for the human.
4. **Run the critical pass over your own findings (step 8.0).** Mandatory: in the first
   field run three of five findings collapsed on re-check.
5. Produce both deliverables: the report file on the machine and the short chat summary.
6. Run the self-check in section 12 before you hand anything over.

## Hard rules

- **Measure first, fix second.** Never in the other order.
- **The whitelist is closed.** Install plugins, apply the shared context, create missing
  directories and memory cards, write the user profile — that is all. No deleting,
  no moving, no rewriting existing files, no git history, no secrets, no pushing,
  nothing sent outside.
- **Never print secret values** anywhere: counts and key names only.
- **A claim without command output is a hypothesis, not a finding.**
- **Name your blind spots**, and label numbers from partial data as lower bounds.

The report and the summary are written in Russian.
