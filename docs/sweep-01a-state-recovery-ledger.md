# Sweep-01a state recovery ledger

Status: automated complete; owner click-later review queued
Updated: 2026-08-31

This ledger records the automated state-recovery pass for every primary route
family. It uses only reserved synthetic identifiers and fictional fixtures. No
provider transcript, credential, workspace content, real model, MCP process,
native approval or accelerator was used.

## Cross-route contracts

| State | Required behavior | Evidence | Status |
| --- | --- | --- | --- |
| Direct URL | Resolve one allowlisted screen, correct title and one navigation owner | Typed manifest plus 27-shape traversal | Green |
| Browser history | Popstate changes the rendered screen, title, focus and navigation owner together | Browser platform unit tests plus integrated App history traversal | Green |
| Unknown URL | Render content-free Not Found; never echo the path; offer Overview and Discovery exits | Parser, browser platform and App tests | Green |
| Route loading | Named, polite, atomic status while retaining truthful shell location | App lazy-route test and traversal | Green |
| Route failure | Hide thrown detail; retry the exact bundle; offer only truthful exit/reload actions | Route boundary and retryable-lazy tests | Green |
| Empty/closed | Preserve unknown versus zero and explain the next available action | Per-surface state pack | Green |
| Service unavailable | Keep the selected screen open, expose an explicit recheck and hide transport detail | App local-health tests | Green |
| Stale response | Abort superseded work and ignore late success or failure | App and per-surface cancellation tests | Green |
| Error recovery | Every shared `ErrorState` has an explicit recovery action | TypeScript source contract plus rendered interaction tests | Green |
| Disabled prerequisite | Every settled disabled control has an accessible reason in synthetic and local-real compositions | Shared rendered control audit across all direct route shapes plus local-real Agent, Models, Prompt Check, Job Centre and Data Source routes | Green |

## Route-family state packs

| Group | Surfaces exercised | Representative boundaries |
| --- | --- | --- |
| Shell and bootstrap | App, bootstrap, browser history, live window | load, startup failure, unknown URL, service checking/offline/recheck, stale health, child-window failure |
| Review workflow | Discovery, reviewed task, task flow, prompt check, calibration | empty, invalid response, unavailable model, retry, polling race, route replacement |
| Catalog and workspace | Projects, Sessions, project workspace and metrics | empty catalog, partial pages, missing project/session, metric-read failure, exact retry, aborted read |
| System workflow | Data source, Job centre, Methods & models, project automation, Models | synthetic closed gates, loopback unavailable, bounded retries, stale receipts, missing runtime |
| Collaboration | Team and Social | capability loading/failure, closed scopes, invalid payload, empty collections, retry |
| Agent workspace | retained projects/chats, model lifecycle, artifacts, diffs, MCP Store/connections/runtime, turn details | unavailable history, disconnected runtime, cleanup block, stale mutation, content-free failure, explicit retry |

The focused state packs passed **637 tests in 28 files**. The shared route and
control contract pack separately passed **42 tests in 3 files**. These are
focused checkpoint counts, not a substitute for the complete frontend and
backend regression gate in Sweep-01a.4.

## Defects repaired in this pass

1. Unknown paths previously resolved silently to Discovery. They now resolve
   to a content-free Not Found screen with two working exits.
2. Browser-platform popstate ownership previously retained a permanent
   listener. It now attaches for the first subscriber and detaches after the
   last subscriber.
3. Four initially disabled controls lacked accessible prerequisite text:
   Discovery merge, Task Flow reset, Social local add and Social file offer.
4. Stored session-metric read failures had no recovery action. They now retry
   the exact selected session without exposing the thrown detail.
5. Missing project and missing selected-session states now provide direct,
   tested exits to Projects or the exact project's Sessions view.
6. Stable local-real prerequisite states now explain why Agent runtime actions,
   model placement/import actions, Prompt Check submission, Job Centre paging,
   Data Source analysis/label actions and Claude capture indexing are disabled.
7. Every repaired prerequisite has a direct transition assertion proving the
   control becomes available when its exact requirement is satisfied.

## Exit evidence

Sweep-01a.4 and Sweep-01a.5 are green. Complete regressions, production build,
generated API, privacy, compile, lock and whitespace checks passed; the rebuilt
loopback application was traversed without protected actions. Exact counts and
the owner click-later list are recorded in the
[checkpoint handoff](checkpoint-sweep-01a-handoff.md).
