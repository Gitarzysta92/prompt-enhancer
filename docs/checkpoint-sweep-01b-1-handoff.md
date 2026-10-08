# Checkpoint Sweep-01b.1 handoff

Status: automated and rebuilt-browser complete; owner review queued
Closed automatically: 2026-08-31
Entry: [Sweep-01b entry](checkpoint-sweep-01b-entry.md)

## Delivered

- Added one shared legibility scale: 12 px caption, 13 px label and 14 px body.
- Added a shared 44 px control/touch target.
- Applied those contracts to the central Agent project rail, retained-chat
  frame, runtime/context card and readiness surface.
- Raised nested retained-workspace paths to the caption floor instead of
  shrinking inline code below its parent metadata.
- Raised all central Agent `.button` actions and project/chat menu triggers to
  the shared target without changing their behavior or labels.
- Added a regression contract that rejects future hard-coded font sizes below
  the caption floor in the four core Agent stylesheets.

## Verification receipt

- Focused Vitest: 14 passed in `AgentPage.layout.test.ts`.
- Complete frontend regression: 2,667 passed across 182 files; 0 failed.
- Production build: 570 modules transformed; build passed.
- Known non-fatal Agent/PDF chunk warning remains assigned to Sweep-01c.
- Rebuilt local Agent at 350 px: 0 visible text elements below 12 px, 0
  undersized core controls, no horizontal overflow.
- Rebuilt local Agent at 1440 px: the same three checks remain green.
- Loopback service remained read-only for this slice; no model was started.

## Owner click-later review

1. Open Agent at phone width and compare the project/chat rail and Model &
   context card with the previous dense presentation.
2. Open Agent settings and confirm readiness labels are legible without making
   the drawer feel inflated.
3. At desktop width, confirm the larger metadata still leaves the conversation
   as the visual priority.

## Remaining Sweep-01b work

This handoff closes only 01b.1. Agent secondary surfaces, all other route
families and the complete accessibility/responsive matrix remain open in
[Sweep-01b](checkpoint-sweep-01b-entry.md).
