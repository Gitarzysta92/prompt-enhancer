# Checkpoint 13 handoff

Status date: 2026-08-25

Status: **UI-00 application shell and shared-primitives repair complete; owner
visual approval remains pending**

The previously completed branch history through `a3578a4` was pushed before
this slice began. Checkpoint 13 then repaired the application-wide shell and
primitive foundation so later card work has stable navigation, focus, modal,
loading, unknown-value, and responsive conventions.

## Accepted implementation

- Desktop has grouped vertical navigation with owned overflow, visible current
  route, and a fixed privacy/runtime footer.
- Mobile has a compact truthful header and a scroll-contained navigation
  dialog instead of a fifteen-item horizontal strip.
- Bootstrap and route failures render safe recovery states; successful retry,
  browser Back, same-route navigation, malformed paths, and responsive-shell
  transitions have explicit focus/history ownership.
- Nested dialogs now share one logical, visual, pointer, and accessibility
  stack; lower layers are inert and hidden until restored.
- Loading, empty/closed, coverage, progress, tab, neutral, and unknown status
  semantics no longer manufacture zero or conflate ordinary state with missing
  evidence.
- Mobile reviewed-task progress remains visible after the drawer closes, and
  all mobile navigation copy retains a 12 px floor.

## Validation checkpoints

- Initial focused gate: **84/84**.
- Final targeted shell/platform/dialog gate: **44/44**.
- Focused responsive browser gate: **16/16**.
- Complete frontend unit gate: **1,321/1,321** across **118/118 files**.
- Complete synthetic Chromium gate: **49/49**.
- TypeScript/production build, API drift, privacy scan, and whitespace checks:
  **passed**.
- Two independent final read-only confirmations found no remaining shell or
  primitive blocker.

The first browser pass exposed a real Chromium interaction: calling
`scrollIntoView()` on the active desktop destination changed sequential focus
navigation and bypassed the skip link. The final implementation scrolls only
the navigation container by the needed delta; both deep-route visibility and
the skip-link contract now pass. A later full browser pass caught two stale
pre-repair tests and one real 360 px section-label font defect; those exact
issues were corrected before the single final 49-test matrix passed.

## Review state

- A synthetic desktop/mobile visual inspection confirms contained navigation,
  visible runtime/privacy truth, current-route focus, 12 px drawer labels, no
  horizontal overflow, and a locked/inert modal background.
- The production app was rebuilt and reloaded at `127.0.0.1:8765/overview`
  without reading private runtime content.
- A fictional synthetic review tab remains available at
  `127.0.0.1:4173/overview`.
- The owner has not yet visually approved UI-00. The next review checkpoint is
  the UI-00 spot-check followed by UI-03 model-ensemble shell review.

## Deferred, not lost

- The Overview route's tight left gutter and card-icon semantics are recorded
  for UI-13.
- Card-specific meta-prompting, metric computation, repeated icons, hierarchy,
  and state design remain in the dependency-ordered UI-03 through UI-20
  backlog.
- No screenshot baseline was added because stable pixel comparison still needs
  pinned fonts and rendering platforms.
