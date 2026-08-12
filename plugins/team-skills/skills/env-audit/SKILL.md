---
name: env-audit
description: Audits a person's working environment end to end — what the agent's instructions claim versus what it actually loads (skills, memory, MCP), where secrets live and what leaks into context, machine resources, and working practices — then writes a report file and a short chat summary with a prioritised fix plan. Strictly read-only, it changes nothing. Use when the user says "/env-audit", "проведи аудит окружения", "проверь моё окружение", "почему агент выдумывает", "агент не помнит", "audit my setup", "проверь настройки агента", or hands over the audit brief to run.
---

# /env-audit — audit the working environment, change nothing

The full brief lives in **`audit-brief.md`** next to this file. It is written in Russian,
addressed to you, and it is the authority: follow it step by step rather than improvising
your own audit.

## How to run

1. Read `audit-brief.md` completely before touching anything. Sections 0–2 define your role,
   the protocol, and the team standard you compare against; sections 3–7 are the phases;
   section 9 lists the traps that make audits produce confident wrong answers.
2. Work through the phases in order, saving every command's output as you go.
3. Produce both deliverables: the report file on the machine and the short chat summary.
4. Run the self-check in section 12 before you hand anything over.

## Hard rules

- **Read-only.** The only files you may create are the report and the raw-facts file.
  No fixes, no cleanups, no "obvious" one-line corrections — those go into the plan instead.
- **Never print secret values** anywhere: not in chat, not in the report, not in the raw facts.
  Counts and key names only.
- **A claim without command output is a hypothesis, not a finding.**
- **Name your blind spots.** Anything you could not see (no root, another user's files) is
  stated explicitly, and numbers derived from partial data are labelled as lower bounds.

The report and the summary are written in Russian.
