# Checkpoint Sweep-01a handoff

Status: automated implementation complete; owner click-later review queued
Closed automatically: 2026-08-31
Parent goal: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md)
Entry: [Sweep-01a entry](checkpoint-sweep-01a-entry.md)
Route/control ledger: [Sweep-01a route and control ledger](sweep-01a-route-control-ledger.md)
State ledger: [Sweep-01a state recovery ledger](sweep-01a-state-recovery-ledger.md)

## Outcome

The route, control and recovery checkpoint is automated-complete. Every
supported route family has one typed owner; unknown paths no longer silently
render Discovery; browser history keeps path, title, focus and navigation in
sync; every settled disabled control found by the synthetic and local-real
audits has an explicit prerequisite; and each repaired prerequisite has a
direct enabled-transition assertion.

This does **not** close the product goal. Sweep-01b still owns the complete
responsive visual/accessibility system, Sweep-01c owns bounded large-state
performance, and Acceptance-01 still owns physical real-model, native-dialog
and trusted-MCP evidence.

## Repairs delivered

1. A typed manifest now owns all 22 route families and 27 supported direct
   shapes, including shell/screen title ownership and chrome-less child routes.
2. Unknown or malformed paths render a content-free Not Found screen with two
   truthful exits and no invalid-path echo.
3. Browser history subscription now attaches and detaches with its actual
   subscribers instead of retaining a permanent listener.
4. Native buttons, links, accessible names, permanent disabled reasons and
   retryable shared error states have source-level contract checks.
5. The rendered audit covers synthetic routes plus the local-real Agent,
   Models, Prompt Check, Job Centre and Data Source compositions.
6. Local-real prerequisites now explain Agent runtime Apply/Stop, model
   placement and registration inputs, installed starting points, Prompt Check
   submission, Job Centre pagination, Data Source analysis and label discovery,
   and Claude capture indexing.
7. Project/session metric recovery, missing-project exits, stale reads and
   content-free route failures have exact retry or recovery actions.
8. Two timing-sensitive assertions now wait for their authoritative settled
   state: replacement requirement/action authority and rejected stale Agent
   context evidence. Both had passed alone but could race under full-suite load.

## Automated gate receipt

| Gate | Result |
| --- | --- |
| Complete frontend | 2,666 passed in 182 files; 0 failed |
| Complete backend | 5,122 passed; 9 expected Windows symlink skips; 0 failed |
| Focused route/control regression | 142 passed in 7 files after the local-real expansion |
| Focused state recovery | 637 passed in 28 files |
| Production frontend | Green; 570 modules transformed |
| Generated API contract | Green |
| Python compile | Green |
| Offline dependency lock | Green; 95 packages |
| Privacy/secret scan | Green |
| Whitespace validation | Green |

The production build still reports the known non-fatal large Agent/PDF chunk
warning. That is recorded for Sweep-01c; it did not hide a build failure.

## Rebuilt loopback receipt

- Fourteen top-level local routes settled with one H1, one active navigation
  owner, a nonblank main region, no duplicate IDs and zero unexplained disabled
  controls.
- Back and Forward restored the correct path, title, H1 and active navigation
  owner.
- At a 360 px requested viewport, Overview, Projects, Agent, Models and Data
  Source had no document-level horizontal overflow or main-content escape.
- Browser diagnostics contained zero console errors and zero warnings.
- The browser-control client blocks arbitrary unknown URLs before the page can
  receive them. Unknown-route rendering and path non-disclosure therefore use
  the deterministic integrated browser-history test rather than a misleading
  live claim.
- The local health route returned HTTP 200 through exactly one loopback
  listener and one listener process.
- The listener process tree had no visible window, no known local-model worker,
  and no process using the GPU. No model was loaded for this checkpoint.

## Safety boundary

Only fictional fixtures, structural page facts and content-free process counts
were used. No provider transcript, private workspace content, credential,
model download, model inference, MCP host or protected approval was opened or
mutated.

## Owner click-later list

1. Reload once and click the top-level destinations, then Back and Forward.
2. On Agent, confirm the Model & Context card makes Apply/Stop prerequisites
   understandable without competing with the chat.
3. On Models, clear and refill the repository, folder and GGUF path fields and
   confirm the exact action enables at the expected point.
4. In Data Source → Advanced source maintenance, confirm consent and selection
   prerequisites for analysis and missing-label discovery read naturally.
5. Note any hierarchy, icon, spacing, focus or narrow-layout issue for the
   next Sweep-01b visual/accessibility pass.

## Next checkpoint

Sweep-01b is next: unify hierarchy, typography, spacing, icon ownership, focus,
status language, forced-colors and reduced-motion behavior across the 320, 360,
768 and 1440 px matrix without removing the feature depth validated here.
