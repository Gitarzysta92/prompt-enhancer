# MCP Store checkpoint 06e.4 handoff

Date: 2026-08-31
Status: automated implementation complete; owner protected/visual review pending
Runtime effect of the automated gate: synthetic in-memory MCP fixtures and a
read-only reload of the rebuilt Agent route only; no real model or MCP host was
started, no external tool was called, no approval was granted and no GPU
workload was created

## Outcome

One managed MCP request is now one first-class Agent timeline card. It uses the
reviewed server and tool names instead of exposing the model-facing `mcp_…`
alias, keeps the exact model call identity across request, approval, resolution
and result, and presents fresh one-call authority, ordered progress, bounded
live output and content-free terminal evidence without turning the chat into a
second MCP Store.

Denial, approval timeout, Stop, tool-reported errors, failures, interruption and
cleanup uncertainty remain distinct. Retained history keeps only safe identity
and receipt facts; raw arguments, approval previews, result text and reusable
authority do not survive.

## Changed

- Added strict `agent-mcp-tool.v1` and `agent-mcp-tool-result.v1` projections to
  the backend, OpenAPI export, generated TypeScript and strict frontend parser.
- The projection carries only reviewed display identity, exact call linkage,
  bounded byte/digest/error/cleanup facts and literal privacy invariants.
- Managed MCP execution now emits the same safe descriptor through native
  approval and the terminal result. Approval event arguments remain empty.
- Durable Agent history stores safe identity and content-free evidence while
  stripping the redacted preview and ephemeral result text.
- Added an exact-call collector and compact MCP activity card. Adjacent calls
  using the same tool cannot merge, and a descriptor-preparation failure still
  settles the already-observed request instead of remaining stuck.
- Added friendly one-call approval copy and explicit approve/deny labels. The
  model alias is hidden from the normal conversation card.
- Added immediate **Cancelling**, retained **Interrupted**, **Not approved**,
  timeout, tool-error, failed and cleanup-uncertain states.
- Added expandable progress and result details, copy support, accessible names,
  responsive layout and forced-colors treatment.
- Added a synthetic browser fixture that denies by keyboard and renders a
  completed receipt without contacting an MCP server.

## Automated evidence

- Direct receipt/privacy invariants: **66 passed**.
- Affected backend Agent/history/catalog/managed-runtime/OpenAPI matrix:
  **168 passed / 6 files**.
- Affected strict-contract, history, activity, effects, layout and Agent-page
  frontend matrix: **186 passed / 6 files**.
- Complete Agent frontend feature regression: **507 passed / 31 files**.
- Rendered keyboard denial and completed-result journeys at **360 px and
  1440 px**: **2 passed**.
- TypeScript project build and production Vite build: passed.
- Generated OpenAPI/TypeScript consistency check: passed.
- Repository privacy scanner: passed after final code and fixture changes.
- Rebuilt live `/agent` route: loaded with its durable project/chat surface and
  **0 browser warnings or errors**.

All new fixtures use reserved fictional identities, paths, calls and results.
No provider transcript, credential store, private workspace content, real MCP
package, model or accelerator workload was read or invoked.

## Process and privacy evidence

- Exactly **1** service listener remained at `127.0.0.1:8765`, loopback only.
- The listener had **0** descendants.
- The temporary synthetic Vite listener at port 4173 was stopped; **0** test
  workers remained.
- **0** model or MCP host processes and **0** numeric GPU compute-memory
  contexts remained.
- MCP approval arguments were `{}` in Agent events; durable history tests prove
  the synthetic raw-result canary and raw `arguments` field are absent.

## Explicit red-evidence ledger

No Store-06e.4 gate remains red.

The first two-width browser run used the generic `cancelled` state in its new
denial fixture. The real backend contract settles a person-denied call as
`not_approved`; the screenshot therefore truthfully showed **Cancelled** while
the assertion expected **Not approved**. The fixture was corrected to mirror
production and both widths passed. Product behavior was not weakened.

An exploratory `privacy_scan.py --help` command was interpreted by that simple
script as a path named `--help` and exited before scanning. The documented
no-argument repository scan was then run and passed. A previous long frontend
run whose wrapper lost its final output was superseded by the captured 186-test
affected matrix and the captured 507-test Agent regression above.

The production build still reports the existing Agent chunk-size advisory.
That non-failing performance debt remains assigned to Sweep-01c; it is not
relabelled as a Store failure.

## Still bounded

- Real approval and actual external tool effects require the owner's deliberate
  trusted-server walkthrough; automation did not manufacture that authority.
- Registry/icon/source hostility belongs to Store-07a.
- Redirect, proxy, DNS, TLS, SSE/HTTP and stream hostility belongs to Store-07b.
- Hidden-window, child-process, crash, flood and Stop-race hostility belongs to
  Store-07c.
- Schema bombs, alias collisions, output floods and approval replay belong to
  Store-07d; secret leakage and cross-project/client isolation belong to
  Store-07e.

## Owner click-later ledger

1. Open a durable project chat with one trusted admitted MCP tool and confirm
   its friendly name is visible under **Project tools**.
2. Ask the model for one harmless tool call and confirm one compact card and one
   native **Approve one call / Deny call** review appear.
3. Deny the first call and confirm it settles as **Not approved / Not invoked**
   with no external effect and no repeated terminal window.
4. If separately trusted, approve one harmless call and inspect its ordered
   progress, bounded result, effect caveat and cleanup evidence.
5. Repeat once with **Stop**, then switch chats and restart the app; confirm no
   pending authority or raw result follows the call into another chat/history.

## Next checkpoint

Store-07a is active next: make poisoned Registry metadata, icons, pagination,
identity/version collisions and source disagreement fail closed with bounded,
content-free diagnostics and usable recovery UI.
