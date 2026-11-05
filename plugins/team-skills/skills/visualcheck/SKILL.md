---
name: visualcheck
description: >
  Visual UI check — analyzes screenshots, mockups, and components for layout bugs,
  UX problems, and design inconsistencies. Use this skill when the user
  asks to check the UI, look at the layout, find visual bugs, says
  "/visualcheck", "проверь UI", "посмотри на интерфейс", "визуальная проверка",
  "что не так с вёрсткой", "проверь дизайн", "visual check", or uploads screenshots
  for review. The skill analyzes desktop and mobile states, checks for common
  UI bugs, and records the results with a severity.
  If the project or the user has its own `visualcheck` skill, that one takes precedence — use this one only when the user typed `/team-skills:visualcheck` or no such skill exists.
---

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:visualcheck` and a skill named `visualcheck` exists in the project (`.claude/skills/visualcheck/SKILL.md`) or in the user's skills (`~/.claude/skills/visualcheck/SKILL.md`), stop: tell the user that their own `/visualcheck` takes precedence, and do nothing else.

# Visual Check Skill

Visual UI check based on screenshots or component code. Finds layout bugs,
UX problems, and design inconsistencies.

---

## Inputs

The user provides one or more of:
- **Screenshots** — uploads images to the chat (desktop / mobile / different states)
- **Component code** — JSX/TSX/HTML/CSS files
- **Task file** — to understand what exactly is supposed to work
- **Task number** — `T01`, `T02`, …

If nothing is provided — ask for screenshots or component code.

---

## Execution algorithm

### 0. Gather context

1. Determine **what we are checking**: task, component, page
2. Determine **what is available**: screenshots, code, or both
3. If there is a task file — read the description and the affected components
4. For a task number without an explicit file, use `docs.tasks` from `.claude/team-skills.json` if present. The profile is optional: if it or that key is absent, skip automatic task lookup and report the skipped step. Continue with supplied screenshots/code; never guess a project task path.

---

### Phase 1 — Screenshot analysis (if provided)

If the user uploaded screenshots — analyze them visually against the checklist below.

Check for each provided state:

**Structure and layout:**
- [ ] Elements do not overlap each other
- [ ] No horizontal scroll (especially on mobile)
- [ ] Spacing and alignment are consistent
- [ ] Grid / columns are not broken

**Text:**
- [ ] Text is not cut off (truncation without ellipsis)
- [ ] No overflow beyond the container
- [ ] Fonts are readable, not too small (min. 12px for body text)
- [ ] No orphan words (one word on a line where not expected)

**Images and icons:**
- [ ] No broken images (placeholder or empty square)
- [ ] Icons are the correct size and not pixelated
- [ ] Check alt text if visible in the code

**Interactive elements:**
- [ ] Buttons are at least 44×44px (tap target on mobile)
- [ ] Links are visually distinguishable from text
- [ ] hover/focus states are visible (if present in the screenshots)

**Modals and overlays:**
- [ ] Modals are centered
- [ ] The backdrop correctly covers the content
- [ ] No content sticking out from under the modal

**Mobile (375px):**
- [ ] Content fits without horizontal scroll
- [ ] Navigation is not broken
- [ ] Tables / wide elements are adapted

---

### Phase 2 — Code analysis (if provided without screenshots)

If there is component code but no screenshots — analyze statically:

**CSS / Tailwind:**
- Conflicting styles (contradictory margin/padding)
- `overflow: hidden` that may hide content unexpectedly
- Missing `min-width: 0` on flex children (a classic text bug)
- Hardcoded px sizes where a fluid layout is needed
- Missing mobile-first media queries

**JSX / HTML:**
- Conditional render without a fallback for the empty state
- Missing skeleton/loading state
- Long strings without `truncate` or `word-break`
- Images without `width`/`height` (layout shift)
- Missing `key` in lists

**Accessibility (a11y — basic level):**
- Buttons without `aria-label` if icon-only
- Forms without a `<label>`
- No `alt` on `<img>`

---

### Phase 3 — State scenarios

Mentally (or from the screenshots) check:

| State | What to check |
|-----------|-------------|
| **Empty** | Is there an empty state? Does the layout hold with zero items? |
| **Loading** | Is there a skeleton/spinner? Does loading avoid layout shifts? |
| **Error** | Is the error shown instead of a blank page? |
| **Long content** | Does the layout hold with long text or many list items? |
| **Short content** | Does a single character in a field look correct? |

---

## Classification

| Severity | When |
|----------|-------|
| **UI/HIGH** | Broken layout, inaccessible content, unusable buttons, horizontal scrolling |
| **UI/MEDIUM** | Poor UX, clipped text, missing empty/error states, small tap targets |
| **UI/LOW** | Pixel inconsistencies, minor spacing issues, class naming |

---

## Output format

### Summary

```
## Visual Check — [Название задачи / компонента]

**Проверено:** Desktop / Mobile / [список состояний]
**Найдено:** N UI/HIGH, M UI/MEDIUM, K UI/LOW
**Вердикт:** ✅ OK / ⚠️ Есть замечания / ❌ Критические проблемы
```

### Findings table

```
| ID | Severity | Состояние | Элемент | Описание | Рекомендация |
|----|----------|-----------|---------|----------|--------------|
| V1 | UI/HIGH | Mobile | Таблица тарифов | Горизонтальный скролл, нет адаптации | Добавить overflow-x: auto или перестроить для mobile |
| V2 | UI/MEDIUM | Empty | UserList | При 0 пользователей — пустой div, нет сообщения | Добавить empty state «Нет пользователей» |
| V3 | UI/LOW | Desktop | Кнопка «Сохранить» | Отступ справа 14px вместо 16px | Исправить padding |
```

---

## Rules

- Be specific: name the component / element / state
- If neither screenshots nor code are provided — ask before starting
- If both screenshots and code are present — analyze both; the code gives additional context
- Do not invent problems — only what you see or what clearly follows from the code
- For UI/HIGH — always explain why it blocks the user
