# MCP Store checkpoint 07a handoff

Date: 2026-08-31
Status: automated implementation complete; owner visual review pending
Runtime effect of the automated gate: synthetic Registry, icon, pagination and
browser fixtures plus one read-only reload of the rebuilt Agent route. No real
Registry browse, model, MCP host, package, protected action or GPU workload was
started.

## Outcome

Hostile or contradictory MCP Registry presentation data now fails closed before
it can replace an accepted card, bind a review to a different presentation,
loop pagination, track through query-bearing artwork or silently update an
existing managed plan. Previously accepted cards and prepared plans remain
usable and separate from newer ambiguous evidence.

## Changed

- Registry text validation now NFC-normalizes bounded public text and rejects
  Unicode control/format/surrogate characters and combining-mark floods.
  Markup-like text remains literal data and is never interpreted as HTML.
- Every catalog card carries a 64-hex presentation revision bound to its exact
  name, version, title, description, status, update time, public links and local
  icon identity. Exact review requests must present that revision; list/detail
  disagreement returns a content-free conflict and cannot create a plan.
- Duplicate catalog identities are idempotent only when the complete normalized
  server projection agrees. Contradictory duplicates reject the live page while
  an exact pre-existing cache remains available unchanged.
- Cache format v2 validates bounded queries/cursors, unique identities and an
  exact one-to-one relationship between accepted cards and trusted icon sources.
- Query-bearing artwork is refused. Proxied PNG/JPEG/WebP bytes are bounded and
  checked against declared type, structure and dimensions before browser use.
- Frontend contracts mirror the Unicode, URL, revision and identity boundary.
  Catalog responses must be bound to the normalized requested search.
- Pagination preserves accepted cards, rejects cross-page identity replacement,
  detects cursor cycles and replayed pages, ignores stale searches and stops at
  32 successful pages. Hostile failures offer an explicit catalog restart;
  transport failures retain exact-cursor retry.
- A prepared managed plan whose plan revision differs from a newer Registry
  review is labelled as a previous plan. The UI can open it for inspection but
  never silently rewrites or re-saves it as current evidence.
- OpenAPI and generated TypeScript now require the exact presentation revision
  on the server-review route.

## Automated evidence

- Focused backend Registry/icon/adversarial suite: **35 passed**.
- Affected backend Registry, management, managed-runtime, host-contract and
  Agent-MCP HTTP matrix: **184 passed / 5 files**.
- OpenAPI export suite: **6 passed**; generated TypeScript API check passed.
- Focused Store contracts, transport and component state machines:
  **64 passed / 4 files**.
- Affected broad HTTP/Registry contract matrix: **224 passed / 4 files**.
- Complete Agent frontend feature regression: **514 passed / 31 files**.
- Normal Store journey at 360 px and 1440 px: **2 passed**.
- Hostile markup/cursor refusal and keyboard restart journey at 360 px and
  1440 px: **2 passed** with no horizontal escape or direct hostile image fetch.
- TypeScript project build, production Vite build, Python compile check, scoped
  diff whitespace check and repository privacy scan passed.
- The rebuilt live `/agent` route loaded its durable project/chat workspace with
  **0 browser warnings or errors**.

All new fixtures use reserved fictional identities, URLs, values and payloads.
No credential store, provider transcript, private workspace content, real MCP
server, model or Registry mutation was read or invoked.

## Process and cleanup evidence

- Final state retained exactly **1** listener at `127.0.0.1:8765`.
- A 12-second, 25-sample follow-up observed **0** listener descendants.
- **0** test workers and **0** model/MCP workers remained.
- **0** Prompt Enhancer-owned GPU compute contexts remained. System-wide GPU
  activity was not treated as owned and was not modified.

One transient `codex.exe` plus `conhost.exe` descendant was observed during a
single post-reload census and had exited before the immediate follow-up. It did
not recur during the bounded monitor. This is not hidden or declared solved; it
is recorded as an explicit Store-07c process/visible-window probe target.

## Still bounded

- Redirects, proxy inheritance, private/reserved DNS, rebinding, TLS/origin
  drift and remote stream hangs belong to Store-07b.
- Hidden-window, child-process, crash, flood and Stop-race behavior—including
  the transient process observation above—belongs to Store-07c.
- Schema bombs, malformed tool traffic and approval replay belong to Store-07d.
- Secret canaries and project/chat/client isolation belong to Store-07e.
- Real protected lifecycle actions and a subjective Store review remain owner
  acceptance work; automation did not manufacture that authority.

## Owner click-later ledger

1. Reload `/agent`, open **Agent settings → MCP Store**, and confirm Browse and
   Managed remain visually separate at the width you normally use.
2. Search for a harmless public server and confirm each tile shows an inert
   local logo or initials, exact name/version and source boundary.
3. Open a review, return to the catalog and load another page if offered; confirm
   focus and prior cards remain stable.
4. If an existing prepared plan is shown after Registry evidence changed,
   confirm it says **Open previous plan** and is not silently updated.

## Next checkpoint

Store-07b is active next: make redirects, proxy inheritance, private/reserved
DNS, rebinding, TLS/origin drift, HTTP/SSE hangs and oversized remote streams
fail closed without retaining an unauthorized connection.
