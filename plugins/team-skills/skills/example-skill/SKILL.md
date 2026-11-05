---
name: example-skill
description: Demonstration skill — a template for creating skills in the team repository. Use when an example structure is needed or the user asks to create a new skill. If the project or the user has its own `example-skill` skill, that one takes precedence — use this one only when the user typed `/team-skills:example-skill` or no such skill exists.
---

# Example Skill

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:example-skill` and a skill named `example-skill` exists in the project (`.claude/skills/example-skill/SKILL.md`) or in the user's skills (`~/.claude/skills/example-skill/SKILL.md`), stop: tell the user that their own `/example-skill` takes precedence, and do nothing else.

This demonstration skill shows the structure and format of a Claude Code skill.

## What this skill does

When activated, Claude will:

- Demonstrate an example skill structure
- Answer questions about how to create a skill

## Example instruction for Claude

Help the user create quality Claude Code skills.
When asked to create a skill, clarify its purpose, then create the structure
with SKILL.md, meta.json and README.md according to the team standard.
