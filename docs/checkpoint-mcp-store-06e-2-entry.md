# MCP Store checkpoint 06e.2 entry snapshot

Date: 2026-08-30
Status at entry: implementation active
Scope: catalog, exact server review, and managed-list presentation only

## Frozen user outcome

A user can understand where every catalog entry came from, distinguish a safe
logo fallback from Registry-proxied artwork, search/filter/sort the entries
already loaded, recover from empty/offline/error/pagination states, inspect
exact compatibility evidence, and continue into the real guarded lifecycle
without contradictory or obsolete controls.

## Authoritative entry findings

- Registry metadata, bounded pagination, cached fallback, raster-only local
  icon proxying, exact review provenance, compatibility reasons, and the full
  managed lifecycle already exist in production contracts.
- The catalog has search and distribution filters but no sort control.
- Initial loading is text-only; search-empty and filter-empty states are not
  distinguished and have no direct recovery action.
- A failed **Load more** request is silent even though earlier cards are kept.
- Managed-list load failure has no retry action.
- Tiles show publisher and management state but do not clearly identify the
  Official Registry as the metadata source or explain whether artwork is a
  safe local fallback.
- Exact review shows compatibility status but does not translate the underlying
  reasons into user-facing evidence.
- Exact review still renders **Install unavailable** and says the guarded
  installer, lifecycle receipts and uninstall path are missing. That copy is
  false: Store-05c/06d already implement guarded install, update, rollback,
  uninstall and recovery behind a saved reviewed plan.

## Bounded implementation

- Add a truthful loaded-result sort control and deterministic ordering.
- Add source/logo provenance and current lifecycle state to compact tiles.
- Add distinct loading, search-empty, filter-empty, cached/offline, partial and
  pagination-failure recovery states.
- Make pagination retry exact and preserve prior results.
- Add managed-list retry and clearer lifecycle/health summaries.
- Translate compatibility status/reasons and route the user to **Save setup
  plan** or **Open managed plan**; remove obsolete installation claims.
- Preserve cancellation and stale-response protection for catalog/review reads.

## Explicit exclusions

- Project permission, host-health and selected-tool reconciliation belongs to
  Store-06e.3.
- In-chat tool availability, approval and activity cards belong to
  Store-06e.4.
- The full hostile registry/logo/network/process/schema matrix belongs to
  Store-07.
- No real package, endpoint, model, provider session, credential or owner file
  is used by this checkpoint.

## Acceptance matrix

- live and cached catalog source;
- safe local-proxy logo and failed-logo initials fallback;
- explicit search plus local/remote filters and loaded-result sort;
- initial loading, no search result, no filter result, invalid contract,
  unavailable Registry and exact retry;
- next-page success, de-duplication, failure, preserved cards and exact retry;
- stale request abort when the query changes;
- review success/failure/retry, provenance links, translated compatibility and
  accurate plan/lifecycle action;
- managed empty/loading/failure/retry and representative planned, installed,
  operation-in-progress and cleanup-required states;
- keyboard behavior, accessible names and 360/1440 px rendered layout;
- affected regression, production build, privacy scan, live loopback/browser
  check and zero-surprise-process census.
