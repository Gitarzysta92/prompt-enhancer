# Checkpoint Sweep-01c.3 handoff

Status: automated and rebuilt-browser complete; owner review queued
Closed automatically: 2026-09-01
Entry: [Sweep-01c.3 entry](checkpoint-sweep-01c-3-entry.md)

## Delivered

- Reconstructed retained conversations through strict monotonic pages bound to
  one immutable `last_seq`. Wrong-chat, changed-head, repeated, out-of-order,
  empty non-terminal and over-100-page histories now fail closed without
  exposing a mixed prefix as conversation history.
- Replaced cumulative transcript expansion with deterministic
  Earlier/Later/Latest navigation over a 200-event window. A nearby user-turn
  boundary may extend the mounted window by no more than 50 events.
- Preserved the independent 40-row project/chat render pages and 50-card
  artifact render pages while exercising all 100-record server continuations.
- Bound delayed project, chat and artifact continuations to an abortable exact
  read owner. A transport that resolves after abort cannot append records into
  a replacement search or lifecycle scope.
- Added a synthetic maximum browser fixture containing 200 projects, 2,000
  chats, 500 artifacts and 4,000 retained events. It uses reserved identifiers,
  fictional labels, fixed timestamps and relative synthetic artifact paths.
- Raised transcript navigation controls to the shared 44 px touch-target floor
  and made large-count formatting deterministic.

## Exact stress receipt

The focused locked-Chromium evidence run recorded:

| Viewport | Loaded / mounted | Activity nodes | Reactions: transcript / project / chat / artifact | Settled CLS |
| --- | --- | ---: | ---: | ---: |
| 360 px | 200 / 40 projects; 2,000 / 40 chats; 500 / 50 artifacts; 4,000 / 200 history records | 202 including navigation/structure | 17.0 / 10.3 / 8.3 / 14.7 ms | 0 |
| 1,440 px | 200 / 40 projects; 2,000 / 40 chats; 500 / 50 artifacts; 4,000 / 200 history records | 202 including navigation/structure | 15.7 / 10.9 / 10.7 / 15.2 ms | 0 |

These are local synthetic regression observations, not field INP claims. Both
views also had zero horizontal overflow, no browser error and a 44 px minimum
height for the transcript navigation control.

## Verification receipt

- Strict retained-history/max-history focused matrix: **3 passed**; 0 failed.
- Complete affected Agent component matrix: **191 passed**; 0 failed.
- Complete frontend regression: **2,720 passed across 184 files**; 0 failed.
- Complete Playwright regression with two bounded workers: **165 passed**; 0
  failed. A final focused two-viewport evidence rerun also passed after the
  metrics annotation was added.
- Sweep-01c maximum MCP, timeline and Agent stress matrix: **6 passed**; 0
  failed.
- Production TypeScript/Vite build passed with **572 transformed modules**.
  The existing non-fatal large Agent/PDF chunk warning remains visible and is
  not represented as fixed by this checkpoint.
- Generated OpenAPI drift, offline lockfile, Python compilation, repository
  privacy and whitespace checks passed.
- Backend production code and schemas did not change in this slice. The full
  backend receipt from Sweep-01c.2 remains the prerequisite and was not
  misleadingly counted as a new run.
- No provider cache, credential, real transcript, workspace file, model, GPU,
  command, MCP host or native confirmation was read or started by the stress
  fixture or its tests.

## Rebuilt local app

- The rebuilt Agent page was reloaded and left open in the in-app browser.
- The live page has one H1, one main region, exact project/chat rows, no
  horizontal overflow, no visible control below 44 px and no browser console
  error.
- `/health` reports `ok`, `offline_only` and `metadata` through exactly one
  listener on `127.0.0.1:8765`.
- The hidden serve parent and its one listener child both have no visible
  window. No `llama-server` or `llama-cli` process remains.

## Owner click-later review

1. Open a retained chat with more than 200 activity records. Use Earlier,
   Later and Latest; confirm only one coherent window is visible at a time.
2. Load a later project/chat page, change search or project immediately and
   confirm no rows from the previous scope appear afterward.
3. Load a later artifact page, switch Active/Archived/Removed immediately and
   confirm the previous lifecycle page cannot append into the new view.
4. At narrow and desktop widths, confirm the page controls feel stable and the
   transcript pager is comfortably clickable.

## Next checkpoint

Sweep-01c is automated complete. Acceptance-01 remains the owner-only queue for
native dialogs, real model placement/switch/unload/VRAM and trusted MCP
click-through. The next automation-safe implementation checkpoint is
Release-01a: migrations, restart recovery, privacy, retention and process
ownership under failure.
