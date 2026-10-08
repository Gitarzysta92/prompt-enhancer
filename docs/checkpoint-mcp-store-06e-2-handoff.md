# MCP Store checkpoint 06e.2 handoff

Date: 2026-08-30
Status: automated implementation complete; owner visual review pending
Runtime effect of the automated gate: synthetic browser fixtures and a read-only
live Store reload only; no plan was saved, no package was changed, no endpoint
was connected, no MCP server or model was started, and no protected authority
was granted

## Outcome

The MCP Store catalog now explains the source and current evidence behind each
entry instead of presenting anonymous tiles or obsolete installation claims.
Users can search, filter and sort the entries already loaded, distinguish a
Registry-declared logo from an initials fallback, inspect translated
compatibility evidence, and continue into the real managed lifecycle.

Loading, search-empty, filter-empty, cached, partial, next-page failure and
managed-list failure states now remain understandable and recoverable. Failed
pagination keeps earlier cards and retries the exact cursor; a newer search
aborts stale work rather than allowing a late response to replace the view.

## Changed

- Compact cards identify the **Official Registry**, version, publisher, update
  date and exact managed lifecycle state.
- Raster artwork remains local-proxy only. Missing or failed artwork receives a
  distinct accessible initials fallback; a declared logo is no longer described
  as successfully displayed after a load failure.
- Browse adds deterministic Registry, name, update-date and managed-first sorts.
  Non-Registry sorts explicitly apply only to entries already loaded.
- Loading skeletons and separate search/filter empty states provide direct
  recovery actions.
- Next-page errors preserve existing cards and expose an exact-cursor retry;
  managed-list errors expose their own bounded retry.
- Exact review translates compatibility status and reasons, expands provenance,
  and removes the false **Install unavailable** / “installer missing” story.
- Review now leads truthfully to **Save setup plan** or **Open managed plan**;
  protected lifecycle actions remain revision-bound and native-confirmed.
- Managed rows expose planned, installed, in-progress and cleanup-required
  lifecycle language plus current compatibility/recovery evidence.
- A dedicated synthetic Store fixture covers real review and saved-plan views at
  narrow and desktop widths without starting a model, package, process or MCP
  connection.

## Automated evidence

- Focused MCP Store component suite: **29 passed**.
- MCP Store plus Agent layout contracts: **42 passed**.
- Registry catalog/review transport and strict frontend contracts: **20 passed**.
- Backend Registry, review, cache, icon-proxy and refusal matrix: **26 passed**.
- Complete Agent frontend feature suite: **481 passed / 28 files**.
- Full frontend suite: **2,512 passed / 175 files**.
- Rendered source/sort/review/managed journeys at **360 px and 1440 px**:
  **2 passed**.
- Production TypeScript/Vite build: passed. The existing large-chunk advisory
  remains a non-failing performance item for Sweep-01c.
- Repository privacy scanner: passed.

All new acceptance data uses reserved fictional identities, hosts, paths and
credentials. No provider transcript, owner credential store, real model, real
package content or unrelated owner file was read.

## Live read-only evidence

- The rebuilt Store reloaded inside the existing Agent route at
  `127.0.0.1:8765` without restarting the service or opening a terminal.
- The live public Registry returned **24** entries with **24** uniquely named
  review controls.
- Loaded-result sorting changed the first card deterministically and disclosed
  its loaded-only scope.
- One public Registry detail rendered source/version provenance, a declared
  setup option, translated compatibility evidence and the guarded-plan
  continuation; obsolete **Install unavailable** copy was absent.
- Managed servers remained a separate workspace and truthfully showed that no
  plan is currently saved. No protected control was invoked.
- Final process census: **1** loopback-only listener, **0** listener descendants,
  and **0** numeric GPU compute-memory contexts.

## Explicit red-evidence ledger

No new Store-06e.2 gate is red. The earlier broad legacy workflow run remains
explicitly unresolved at **66 passed / 16 failed** across eight duplicated
non-Store scenarios at two widths. It was not rerun or relabelled here. Its
Agent/Runtime/Workspace assertion reconciliation remains assigned to Sweep-01a;
the two isolated Store journeys and the complete unit regression are green.

## Still bounded

- Project permission, host-health and selected-tool reconciliation belongs to
  Store-06e.3.
- Compact in-chat tool availability, approvals, activity and result presentation
  belongs to Store-06e.4.
- Poisoned Registry metadata/icons and the full hostile transport, process,
  schema, secret and isolation matrix belongs to Store-07.
- Real save/install/update/rollback/remove/start/tool-call clicks remain owner
  acceptance. Automation did not manufacture protected authority.

## Owner click-later ledger

1. Open **Agent → Agent settings → MCP Store** and confirm source/lifecycle facts
   remain scannable on the cards.
2. Exercise search, distribution filters, sorting and **Load more**.
3. Open one exact detail and check provenance plus compatibility wording.
4. Open **Managed servers** and inspect any trusted plan's lifecycle/recovery
   state.
5. Save or activate only a separately trusted exact option; record the native
   confirmation result without copying secret values.

## Next checkpoint

Store-06e.3 is active: reconcile exact project permissions, saved-plan health,
project admission and selected tools across Store, project and active chat so
stale or cross-project authority disappears immediately and every unavailable
state remains recoverable.
