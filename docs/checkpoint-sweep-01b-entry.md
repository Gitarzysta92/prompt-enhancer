# Checkpoint Sweep-01b entry

Status: automated complete through 01b.4; owner visual review queued; Sweep-01c next
Entered: 2026-08-31
Parent goal: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md)
Prerequisite: [Sweep-01a handoff](checkpoint-sweep-01a-handoff.md)

## Outcome boundary

Sweep-01b makes the complete application visually coherent, responsive and
accessible without removing feature depth or weakening truthful state. It is
not complete until primary journeys pass at 320, 360, 768 and 1440 px in both
themes, keyboard order is deliberate, forced colors and reduced motion remain
usable, and the owner has a short reload-ready visual review list.

## Bounded slices

1. **01b.1 — Agent foundation:** establish shared caption/body/control tokens;
   remove microscopic text and undersized primary controls from the project
   rail, runtime/context card, readiness panel and core conversation frame.
2. **01b.2 — Agent secondary surfaces:** apply the system to settings, MCP
   Store, artifacts, workspace review, attachments and controller panels;
   reduce density through progressive disclosure rather than hidden behavior.
3. **01b.3 — Whole-application hierarchy:** reconcile route headers, cards,
   status language, icons, spacing and primary-action ownership across every
   route family inventoried by Sweep-01a.
4. **01b.4 — Accessibility and responsive closure:** run the 320/360/768/1440
   matrix, keyboard journeys, focus containment/restoration, screen-reader
   names, contrast, forced colors, reduced motion and both themes.

## 01b.1 baseline and result

At a 360 px requested viewport (350 px document viewport), the rebuilt local
Agent page originally exposed 71 visible labels below 12 px; the minimum was
9.28 px. Five central `.button` or project-menu targets were below the shared
44 px target on at least one dimension. There was no horizontal overflow.

The foundation slice adds `--type-caption`, `--type-label`, `--type-body`,
`--control-height` and `--touch-target` tokens and routes the central Agent CSS
through them. A source contract rejects hard-coded sub-caption rem sizes in the
four core stylesheets.

After rebuilding, the same live view reports:

- zero visible central Agent text elements below 12 px at 350 and 1440 px;
- zero undersized core `.button` or project-menu controls at both widths;
- document scroll width equal to viewport width at both widths;
- one visible H1 and no functional behavior change.

## Safety boundary

The slice used retained synthetic project metadata already present in the local
test application. It did not start a model, invoke a protected action, inspect
provider transcripts, install an MCP server or transmit content.

## 01b.3 result

The whole application now shares semantic route headers, bounded route gutters,
12 px caption and 44 px action floors, consistent status and action language,
distinct primary-navigation icons and one primary action owner per local
surface. Twenty-three direct and parameterized route shapes passed exact
settled geometry at 360 px and 1440 px. See the
[01b.3 handoff](checkpoint-sweep-01b-3-handoff.md).

## 01b.4 result

Twenty-six direct and parameterized route shapes now pass 208 settled route
audits across 320/360/768/1440 px and both themes. The same checkpoint proves
keyboard entry and focus behavior at all eight width/theme combinations plus
forced colors and reduced motion at every width. The complete frontend and
Playwright regressions are green. See the
[01b.4 handoff](checkpoint-sweep-01b-4-handoff.md).

## Next checkpoint

Sweep-01b is automated complete. Sweep-01c now tests long synthetic chats,
catalogs, file trees, artifacts and event streams for bounded rendering,
pagination or virtualization, cancellation, stale-response safety and layout
stability. The owner click-later list remains queued as Acceptance-01 evidence.
