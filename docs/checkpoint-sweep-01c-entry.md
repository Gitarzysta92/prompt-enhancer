# Checkpoint Sweep-01c entry

Status: automated complete through 01c.3; owner review queued
Entered: 2026-09-01
Parent goal: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md)
Prerequisite: [Sweep-01b.4 handoff](checkpoint-sweep-01b-4-handoff.md)

## Outcome boundary

Sweep-01c keeps long synthetic chats, project/chat catalogs, workspace trees,
artifact collections and event timelines responsive without hiding partial
coverage, losing the selected item or accepting stale responses. It is not
complete merely because server responses have fixed maximum sizes: mounted DOM,
network paging, cancellation and layout stability each need direct evidence.

## Entry evidence

- Agent history admits at most 4,000 events and already renders a progressive
  200-event suffix, but session-effect summaries still mount every distinct
  reviewed path.
- Workspace discovery and folder views each admit up to 400 entries; discovery
  can additionally mount 400 Git changes in the same drawer.
- Artifact storage admits 500 artifacts per chat while the list endpoint
  returns only the newest 200 and the current card mounts every returned item.
- Durable Agent catalog endpoints return at most 200 projects or chats while a
  repository may retain up to 2,000 chats; the rail mounts every returned row
  and cannot yet request the next page.
- Session timelines admit up to 2,000 turns, tools and markers per collection;
  the full-range SVG can mount all drawable items even though it is labeled
  bounded.
- MCP registry paging is network-bounded to 32 pages, but accumulated filtered
  tiles are not yet render-windowed.

These are synthetic-capacity observations from current contracts and source.
No private project, transcript, workspace path or provider cache was read.

## Bounded slices

1. **01c.1 — Bounded rendering:** add stable render windows or paging controls
   to the large in-memory surfaces, preserve current selection and focus, and
   expose exact shown/available counts.
2. **01c.2 — Durable paging:** add strict offset/cursor contracts for Agent
   projects, chats and artifacts so records beyond the first server page stay
   browseable without duplicate or stale-page acceptance.
3. **01c.3 — Stress closure:** inject cancellation, delayed/out-of-order pages,
   large retained histories and layout observation; record explicit budgets for
   mounted nodes, interaction latency and layout shift at narrow and desktop
   widths.

## Frozen safety boundary

- Fixtures use only reserved synthetic identifiers and fictional relative
  paths.
- No model, MCP host, command, provider transcript or protected write is needed
  to prove this checkpoint.
- Missing or truncated data stays visibly partial; a render window never claims
  that hidden or unrequested records do not exist.
- Selection, approval authority and active operations may not move merely
  because a page or render window changes.

## 01c.1 exit gate

- Maximum admitted synthetic payloads mount within documented per-surface
  limits.
- Earlier/later or show-more controls remain keyboard reachable, announce exact
  counts and preserve the selected project, chat, file, artifact and timeline
  filters.
- Focused component tests, a rendered 360/1440 px stress journey, complete
  frontend regression, production build, API/privacy checks and a rebuilt live
  reload pass.

Closed by: [Sweep-01c.1 handoff](checkpoint-sweep-01c-1-handoff.md)

## 01c.2 exit gate

- Agent projects, chats and artifacts expose exact snapshot-bound server pages
  beyond the first bounded response.
- Mutation, cross-scope replay, duplicate/reordered pages and stale responses
  fail closed without discarding the loaded prefix or moving selection.
- Full backend/frontend/browser/build/API/privacy gates and a rebuilt live
  360/1440 px reload pass.

Closed by: [Sweep-01c.2 handoff](checkpoint-sweep-01c-2-handoff.md)

## 01c.3 exit gate

- Maximum retained history stays within a fixed mounted transcript window and
  every multi-page read binds one immutable history head.
- Delayed, cancelled and out-of-order catalog/artifact continuations cannot
  cross a replacement search, project, chat or lifecycle scope.
- Exact mounted-node, local interaction-latency, horizontal-overflow and
  cumulative-layout-shift budgets pass at 360 and 1,440 px.

Entered by: [Sweep-01c.3 entry](checkpoint-sweep-01c-3-entry.md)

Closed by: [Sweep-01c.3 handoff](checkpoint-sweep-01c-3-handoff.md)
