---
name: dashboards
description: Principles and data sources for building internal dashboards. Use when the user asks to create a new dashboard, add a page showing metrics or system state, says "сделай дашборд", "нужна страница с метриками", "покажи статистику на странице", "добавь дашборд", "/dashboards" — or when reviewing an existing dashboard for the usual failure modes (stale data shown as fresh, empty states rendered as bugs, access decided after launch).
---

# Building an internal dashboard

This skill is not about writing a view. It is about what makes a dashboard
trustworthy, and where the numbers come from in this environment.

It exists because five dashboards were built five times from scratch, each one
re-deciding the same questions. The result was three codebases on two hosts with
four authentication schemes. Every principle below is paid for by an incident.

## Part 1 — Principles

Apply these to any dashboard, in any stack.

### A number without provenance is not a number

Every page states where its data came from and as of when. Always visible, never
in a tooltip.

Why this is rule number one: a mesh dashboard once served silently stale
snapshots, and four days of decisions were made on numbers everyone believed
were live. The fix was a staleness threshold plus a visible line that says the
data is old. Freshness that degrades silently is worse than a page that is down,
because a down page cannot mislead.

Corollary: when the data channel is missing, say so. Never fall back to a local
or cached source and render it as if it were current.

### An empty state is an answer

"No failures in this period" and "the court has not scheduled a date yet" are
results, not defects. Design them as first-class content with real wording.

A blank panel makes the reader assume the page is broken and go ask a human —
which is exactly the work the dashboard was supposed to remove.

### The page must work without JavaScript

The server renders the numbers. Charts are decoration on top of numbers that are
already in the HTML. If a chart library fails to load, the reader still gets the
answer.

Test it by disabling JavaScript, not by intending to.

### An external CDN is a failure point you do not control

No fonts, scripts, or styles from other hosts. Someone else's outage becomes
your outage, and a dashboard is consulted precisely when things are going wrong.

Inline what you need or vendor it.

### Both themes, and get the CSS structure right

The reader has three states, not two: explicit light, explicit dark, and the
default where nothing is stamped and only the OS preference decides.

Declare the complete light palette on bare `:root`. Redefine only the tokens
under `@media (prefers-color-scheme: dark)`, guarded so an explicit light choice
still wins. Redefine them again under the explicit dark selector.

Never let a color's only definition live inside a media query — the classic bug
is one theme's text on the other theme's background, and it appears only for
readers who set a preference explicitly.

### Numbers in human units

Ratios as percentages, milliseconds as seconds, internal keys never shown.
Monospace with tabular figures wherever digits line up in a column, otherwise
they dance on every refresh.

### Access is decided before the first render, not after the demo

Decide who may see the page while designing it. A dashboard that reaches
production open "because we just sent a link" stays open — one of ours was
public for a year that way.

Fail closed: if the answer to "may this person see it" is uncertain, refuse.

### Registration in the hub is part of being finished

A dashboard nobody can find does not exist. Add it to the registry, with an
owner, in the same change that ships it.

### Every dashboard has an owner, and the owner is a person

Not a team. When the page breaks, someone must be called. Pages without a named
owner become nobody's within a few months, and then they rot while still being
read.

### Write for the reader, not the schema

Name things the way people say them. Description lines answer "when should I
come here", not "what is this called". "How many questions the bot closed by
itself" is a description; "bot effectiveness dashboard" is the title again.

## Part 2 — Where the data comes from

Pick the source before designing the page — it decides where the page can live.

| Source | Holds | Read via | Watch out for |
|---|---|---|---|
| Production Postgres | users, action logs, metric snapshots, observability events | Django ORM; from outside prod, a dedicated read-only role over the private mesh network | Never grant a whole schema. Name the tables. If a page needs one flag off a table with personal data, expose a two-column view instead of the table. |
| Dev Postgres | dev contour's own data | Django ORM | **Not a replica of production.** It drifts by weeks. Rendering a dev snapshot as current numbers is the failure mode rule one exists to prevent. |
| Supabase (support project) | chat history, court documents | HTTP + key | Reachable from anywhere with the key, so a page reading only this can live anywhere. Read synchronously from WSGI — async clients in a sync view produce "Event loop is closed". |
| Supabase (electronic case project) | case files, documents | HTTP + key | Separate project, separate key from the one above. |
| CRM REST API | deals, tasks, operator chats | the repo's own client | **Not reachable directly from the dev host** — the uplink filters it, and calls must go through a relay. Check reachability before designing a page around it. |
| Redis | counters, dedup keys, registries | direct | Not durable. Depending on deployment it may have no volume at all, so never treat it as the only home of anything you must show later. |
| Collected node snapshots | hardware and service state | scheduled collector writing to the DB | The collector is a separate moving part. If it stops, the page keeps rendering the last snapshot — which is precisely why the staleness stamp is mandatory. |
| Pushed snapshots | server health | endpoint receiving from a cron reporter | The reporter can go quiet without any error on your side. Absence of a push is information: show it. |

Two questions that decide the architecture:

1. **Is the source reachable from where the page will run?** Some sources are
   host-bound. This is the single most common thing that turns a one-day page
   into a one-week one.
2. **Does the page only read?** A page with buttons — resolve, mute, retry —
   writes. That disqualifies a read-only channel and usually means the page must
   live next to its data. Notice this before promising a move.

## Part 3 — How to build one

### First, one fork

**Is this a page inside an existing app, or its own service?**

- **Inside the app** when it reads that app's data and needs its login. Cheapest
  and the default: a view, a template, a route, a registry entry.
- **Its own service** when it has a different lifecycle, different data, or must
  survive the app being down. Costs a repo, a manifest, a registry record and a
  deploy path — pay it deliberately.

Health-of-the-system pages are the interesting case: they are consulted when
things break, so hosting them on the thing that might be broken is a real
mistake. Prefer the more reliable host even if it splits the fleet.

### Then the checklist

- [ ] Source chosen, reachability from the target host **verified, not assumed**
- [ ] Read-only or read-write settled — buttons decide where the page can live
- [ ] Access decided and fail-closed
- [ ] Shell and theme tokens reused, no new palette invented
- [ ] Provenance and freshness visible on the page
- [ ] Empty and stale states written as real sentences
- [ ] Works with JavaScript disabled
- [ ] No external hosts
- [ ] Registered in the hub with a one-line "when to come here" and a named owner
- [ ] Checked in both themes and at a narrow window

### Reviewing someone else's dashboard

The failures cluster. Look for them in this order: stale data with no stamp;
an empty state that looks like a bug; numbers that only exist in JavaScript; a
palette declared only inside a media query; no owner; not in the hub.
