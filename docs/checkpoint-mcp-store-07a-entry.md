# Checkpoint Store-07a entry

Status: implementation active
Entered: 2026-08-31
Parent goal: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md)
Previous evidence: [Store-06e.4 handoff](checkpoint-mcp-store-06e-4-handoff.md)

## Frozen user outcome

Untrusted MCP Registry presentation data must never make the Store unsafe,
misidentify a server, silently replace a reviewed version, track the user
through artwork, break the layout or strand the catalog in a pagination loop.
Hostile or contradictory entries fail closed with a short recoverable state and
content-free diagnostic; previously verified cards and managed plans remain
usable and are never rewritten from ambiguous source data.

## Evidence at entry

- Store-06e.2 already uses source-provenanced catalog entries, a local-only
  artwork proxy, initials fallback, exact-cursor retry and stale-search abort.
- Strict backend and frontend contracts already bound common field lengths,
  Registry identity and review payload shape.
- Store-06e.3/06e.4 already fail closed when project, tool or call identity
  drifts after review.
- The remaining gap is an explicit adversarial matrix across poisoned display
  strings, hostile artwork references, duplicate/colliding identities,
  pagination replay/drift and disagreement between catalog, detail and managed
  evidence.

## In scope

1. Reject or safely normalize control/bidirectional/invisible characters,
   whitespace abuse, markup-like text, extreme Unicode and oversized display
   metadata without interpreting it as HTML.
2. Keep artwork inert: only the bounded local proxy or accessible initials
   fallback may render; unsupported schemes, credentials, fragments, malformed
   media and identity drift cannot become direct browser fetches.
3. Detect duplicate catalog IDs, server/version identity collisions, exact-card
   replacement, unstable order and conflicting publisher/source facts.
4. Bound pagination count/cursor size, detect cursor cycles and replayed pages,
   preserve already accepted cards on a bad later page and make retry/reset
   deliberate.
5. Reconcile catalog, exact-detail and existing managed-plan evidence. A source
   disagreement blocks save/update continuation instead of silently choosing a
   winner.
6. Emit stable reason codes and bounded content-free diagnostics; hostile raw
   metadata, URLs or response bodies do not enter logs, durable receipts or
   analytics.
7. Prove keyboard, screen-reader, 360 px and 1440 px loading/refusal/recovery
   behavior with synthetic hostile fixtures only.

## Explicit exclusions

- Redirect chains, proxy inheritance, private/reserved DNS, rebinding, TLS,
  origin drift and streaming transport hangs belong to Store-07b.
- Executable/package process behavior, child escape, stderr flood and Stop
  races belong to Store-07c.
- Recursive tool schemas, alias collisions at runtime, argument/result bombs,
  output flood and approval replay belong to Store-07d.
- Secret values, logs, stale vault references, cross-project access and
  concurrent-client isolation belong to Store-07e.
- No real Registry mutation, package install, MCP host, model, protected click
  or remote hostile endpoint is used in this checkpoint.

## Acceptance matrix

| Case | Required result |
| --- | --- |
| Poisoned title/description/publisher | Never interpreted as markup or control flow; card remains bounded or the entry is refused with a stable code. |
| Hostile artwork metadata | No direct browser/network request; fallback identity is accessible and the declared logo is not reported as displayed. |
| Duplicate exact entry | Idempotent only when every identity/version/source fact agrees; otherwise the page is rejected or isolated. |
| Identity/version collision | Review/save/update is blocked and no existing managed plan changes. |
| Cursor cycle or replay | Loading terminates within a fixed bound, accepted cards remain and one explicit recovery path is shown. |
| Late/stale page | A superseded search/filter generation cannot append or replace current results. |
| Catalog/detail disagreement | The conflict is visible, content-free and non-actionable until a fresh coherent review. |
| Oversized/malformed page | Parsing and diagnostics stay bounded; no raw body or hostile value is retained. |
| Accessibility/layout | Refusal and recovery are keyboard reachable, announced once and fit at 360/1440 px without horizontal escape. |

## Expected touched surfaces

- MCP Registry catalog/review/cache/icon validation and reason-code contracts;
- strict API/OpenAPI/frontend Store parsing;
- Store browse/detail refusal and recovery UI;
- synthetic backend, frontend and rendered adversarial fixtures;
- Store-07a handoff and master milestone board.

Any transport, process, schema-runtime, secret or cross-project defect is
recorded under Store-07b through 07e and does not silently expand this packet.
