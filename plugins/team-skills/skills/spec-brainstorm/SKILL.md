---
name: spec-brainstorm
description: Interactive co-creation of a new SUP specification in a question-and-answer mode. Does not generate a spec out of thin air — it guides the person through structured discovery (problem → goal → phases → architecture → risks → DoD), then delegates the final file write to /sup-spec-writer. Use when the user says '/spec-brainstorm', 'давай распишем новую спеку', 'надо подумать над новой спекой', 'хочу набросать SNN', 'обсудим новый спек', 'давай спроектируем фичу', 'распиши со мной', 'набросаем спеку вместе', or when there is a raw idea for a large chunk of work that needs to be turned into SNN_*.md. Fundamentally interactive — asks questions one at a time via AskUserQuestion, does not write the file until the person has finalized the content.
---

# /spec-brainstorm — co-creating a new spec

Specs are strategic decisions. They must not be generated from templates or thin air. This skill guides the person through structured discovery and at the end **hands off the result** to `/sup-spec-writer` to write the file according to project conventions.

**Principle:** you don't write the spec **for** the person. You help them **formulate** it.

---

## How it differs from /sup-spec-writer

| Aspect | /spec-brainstorm (this one) | /sup-spec-writer |
|---|---|---|
| Mode | Interactive, questions → answers | Generative, from an input description |
| When | New idea, no structure yet | Structure is clear, needs formatting |
| Output | Final draft SNN with `status: draft` | File following all conventions |
| Calls | `/sup-spec-writer` at the end | Nothing |

If the person already has a **complete spec description** (in a single message: goal, phases, tasks) — **do not use this skill**, go to `/sup-spec-writer` directly.

---

## Input

- `/spec-brainstorm` — start from scratch, draw the idea out of the person
- `/spec-brainstorm "raw free-form idea"` — start with a seed, then refine

---

## Phase 0 — Read the conventions at runtime

Don't rely on memory. **Read these files** before starting:

1. `docs/4. SUP-guides/specifications_guide.md` — spec structure
2. `docs/4. SUP-guides/doc_conventions.md` — naming, numbering
3. `docs/4. SUP-guides/business_requirements_template.md` — if the spec is high-level and needs a BR linkage
4. `SUP-architecture.md` — where the new spec fits into the overall picture
5. `SUP-HANDOFF.md` — what's in progress right now (not duplicating?)

This is your context. Don't relay it to the user — just use it when formulating questions.

---

## Phase 1 — Understand the problem (NOT the solution)

The most common spec mistake is jumping straight to "how we'll do it" without a clear "why." Start with the problem.

Ask via `AskUserQuestion` (one question at a time, with concrete options):

1. **What problem are we solving?**
   - "The current process X takes Y minutes, needs to be Z"
   - "Managers complain about A"
   - "Clients get lost at stage B"
   - "Metric X is degrading"
   - Other (free-form)

2. **Who is suffering right now?**
   - Bot clients
   - Managers (internal)
   - Me as the developer (tech debt)
   - The business (revenue/conversion)
   - Several (multi-select)

3. **What happens if we DON'T do it this quarter?**
   - Nothing critical — backlog
   - Tolerable for another month or two
   - Problems pile up every day
   - Already on fire

If the person answers "I don't know" or the answers are inconsistent — **stop and flag it**. A spec without a clear problem will turn into a bad task.

---

## Phase 2 — Formulate the goal and constraints

Now that the "why" is clear, draw out the **what** in a single sentence:

**"Goal: <verb> <object> so that <metric/outcome>".**

Example: "Reduce AI-chat response time from 12s to 5s so that clients don't leave for TG."

Ask:

1. **What is the measurable outcome?** The metric that will show it worked.
2. **What is NOT in scope?** The most important part — what we deliberately won't do. Without this the spec will sprawl.
3. **Are there hard constraints?** Token budget, deadline, can't touch the prod DB, can't break the client API, etc.

Save the answers to your context. **Read the summary back to the person** — "did I get it right? goal X, outcome Y, not doing Z, constraints C" — and ask them to confirm or adjust.

---

## Phase 3 — Architectural sketch

At this point you have the problem, the goal, and the boundaries. Time to sketch the "how."

1. **Which layers will we touch?** (multi-select)
   - TG bot / MAX bot (`tg_bot/`, `max_bot/`)
   - Django (models, migrations, API — `Handler/`, `Tracker/`)
   - AI pipeline (`shared/ai_pipeline/`)
   - Bitrix integration (`bitrix/`)
   - External services (Supabase, OpenAI, Tochka)
   - Infra (docker, CI, migrations)
   - Documentation

2. **Natural phase boundaries?** Options based on the layers:
   - One phase: everything at once, small scope
   - Two phases: data + UX
   - Three+ phases: data → integration → UX → polish

3. **What new models / migrations will there be?** (if applicable) — briefly. If there are any — that's a serious risk, it needs a separate task tagged `require_human_approval`.

4. **What could go wrong?** Name 2-3 risks off the top of your head — needed for the DoD section.

If the person is stuck — **offer 2-3 architectural options** based on what you read in `SUP-architecture.md`, and ask them to choose. Don't make things up — use the project's patterns.

---

## Phase 4 — Definition of Done

A spec without a clear DoD = a constant "just one more little task." Ask:

1. **What are the "done" criteria?** (multi-select + Other)
   - Metric X reached Y
   - All tasks closed + reviews passed
   - Prod-deployed and didn't break for N days
   - Managers tested and confirmed
   - User testing on dev

2. **Who gives final acceptance sign-off?** You yourself? A manager? The client? (important — determines when the spec is `status: done`)

---

## Phase 5 — Finalize into a draft

Now you have in your context:
- Problem + who's suffering + urgency
- Goal + metric + what-we-won't-do + constraints
- Affected layers + phases + risks
- DoD

**Show the person a summary as a draft structure:**

```markdown
# SNN_<slug>: <one-sentence goal>

## Проблема
<2-3 строки>

## Цель
<одно предложение>

## Скоуп
**В скоупе:** <список>
**Не в скоупе:** <список>

## Фазы
1. <Phase 1 name> — <что делаем>
2. <Phase 2 name> — ...

## Архитектура
<какие слои, какие новые модели/миграции>

## Риски
- <risk 1>
- <risk 2>

## DoD
- <criterion 1>
- <criterion 2>

## Связанные документы
- <SUP-BRNN_xxx если применимо>
- <ссылки на прошлые SNN>
```

**Ask:** "Is this final? Ready to hand off to /sup-spec-writer to write the file? Or shall we iterate more?"

If there are edits — iterate. If it's OK — move to Phase 6.

---

## Phase 6 — Delegate the file write to /sup-spec-writer

**Don't write the file yourself.** Call `/sup-spec-writer` via the Skill tool, passing it the final summary as input.

Call contract (in a single message to it):
```
Create a new specification from the following draft.
Status: draft (not active!) — human confirmation is required before launching tasks.
Next SNN number — determine it by scanning docs/2. SUP-specifications/ + docs/backlog/.

<insert the entire summary from Phase 5>
```

After /sup-spec-writer returns the file — **read it** and show the person:
```
✅ Spec created: docs/2. SUP-specifications/SNN_<slug>.md
   Status: draft

Next steps:
1. Review the file — especially the numbering (SNN) and the wording
2. When ready — promote it to `status: active` (edit the YAML frontmatter)
3. Once active, /auto-pilot can decompose it into TNN tasks on its own
```

---

## What NOT to do

1. **Don't ask more than 2-3 questions in a single `AskUserQuestion` block.** Better to go sequentially, so each answer informs the next.
2. **Don't propose a "solution" until the "problem" is nailed down.** This is a typical mistake.
3. **Don't write the file directly** — always via `/sup-spec-writer`. Conventions evolve, and a single write point enforces them.
4. **Don't set `status: active` automatically.** Only `draft`. The person promotes it to active when they're ready to hand it off for work.
5. **Don't decompose into TNN tasks in this skill.** Decomposition is a separate step (via `/sup-spec-writer` or `/auto-pilot` Rule 4).
6. **Don't try to "extract" a spec that isn't ripe yet.** If after Phase 1 it's clear the person isn't sure about the problem — better to say "let's come back when it's clearer."

---

## Edge cases

**The spec already partly exists in `docs/backlog/`** — ask the person whether we activate that one or create a new one. If we activate — skip Phases 1-4, go straight to Phase 6 with additions.

**This is a small single-task feature** — no spec needed. Suggest to the person: "This is TNN level, not SNN. Create a task in the existing spec S0X?" and go to `/sup-spec-writer` with type T.

**The topic overlaps with an active spec** — flag it after Phase 0 ("this looks like work in S08, are you sure a separate SNN is needed?") — let the person decide.

---

## Links to other skills

| Skill | When |
|---|---|
| `/sup-spec-writer` | Phase 6 — final file write |
| `superpowers:brainstorming` | Can be plugged in as a stylistic reference for discovery in Phases 1-3 |
| `/auto-pilot` | NOT directly — but the draft spec created will feed into its Rule 4 for auto-decomposition |
