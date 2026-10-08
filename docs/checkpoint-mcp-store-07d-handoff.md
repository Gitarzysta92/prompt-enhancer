# MCP Store checkpoint 07d handoff

Date: 2026-08-31
Status: automated implementation complete; owner protected-action review pending
Runtime effect of the automated gate: synthetic schemas, tool contracts,
arguments, approvals and results plus read-only inspection of the already-running
loopback application. No real MCP package or host, local model, protected action,
credential, private workspace content, GPU workload or new application process
was started.

## Outcome

The admitted MCP tool boundary is now finite and fail-closed. A server cannot
publish recursive or ambiguous tool contracts, smuggle malformed arguments,
replay an approval, change the reviewed contract before dispatch, or retain an
oversized/malformed result. Each approved call is bound to the exact reviewed
scope and may be claimed once; Stop, drift and settlement remove authority
instead of leaving a reusable approval behind.

## Changed

- Tool discovery now has explicit schema byte, depth, node, collection,
  property, branch, enum, string and pattern budgets. Only the documented JSON
  Schema vocabulary, dialects, formats and a conservative regular-expression
  subset are accepted.
- Local references are resolved against the reviewed document. Missing,
  malformed, external and recursive references fail the entire tool contract;
  boolean schemas and bounded definitions are preserved rather than silently
  projected away.
- Tool identity is canonicalized once. Exact, case-folded, Unicode, separator,
  reserved-name and model-facing alias collisions fail closed before any
  ambiguous tool is exposed.
- Detached JSON arguments reject duplicate keys, non-finite values, excessive
  bytes/depth/items and schema-invalid values before approval. Dispatch is
  still bound to the exact reviewed argument and schema digests.
- Fresh approval claims are durable, expiring and one-use. The claim is settled
  atomically before dispatch, so concurrent callers cannot both spend the same
  approval. A second browser decision also fails as already settled instead of
  changing an earlier decision.
- Result projection has finite content, item, nesting, text and structured-data
  budgets. Contradictory, unsupported, malformed and oversized results close as
  bounded safe failures without retaining raw output.
- HTTP error mapping and frontend transports expose only allowlisted schema,
  identity, replay, settlement, cleanup and result categories. The Agent plan,
  approval and activity views now provide fixed recovery guidance and refresh
  away stale approval cards without rendering private detail.
- Database schema 28 adds content-free one-use MCP tool-call claims and exact
  receipt binding. Upgrade fixtures now reconstruct the real pre-28 schema
  before testing migration.

## Regression repaired during the gate

The broad migration matrix initially found four fixtures that claimed to model
an older database while retaining the new claims table. Their downgrade helper
now removes that table first. The isolated four cases and the complete affected
backend matrix returned to green without weakening the migration or replay
contract.

## Automated evidence

- Focused guarded-host, managed-runtime, server-management and local-Agent
  matrix: **186 passed, 72 deselected**.
- Broad MCP, Agent, retained-history and OpenAPI backend matrix across 16 test
  files: **476 passed**.
- Broad Agent, MCP and shared API frontend matrix: **803 passed / 37 files**.
- Production frontend build passed. The existing AgentPage chunk-size warning
  remains recorded for the later performance sweep; it is not a correctness or
  privacy failure in this packet.
- Generated API check, Python compile check and repository privacy scan passed.
- Synthetic canaries remained absent from safe API and UI error projections.

## Read-only live browser evidence

The existing `http://127.0.0.1:8765/agent` tab was reloaded after the build.
Projects/chats, the stopped shared runtime, Agent settings, readiness, MCP Store
and Managed servers rendered with **0 browser console errors**. Readiness showed
16/16 implemented capabilities while keeping ten owner-only checks visibly
pending.

The external Registry catalogue was unavailable during the smoke. The Store
failed closed with a fixed retry path and the explicit statement that no
installation was attempted. The Managed view remained usable and truthfully
showed zero saved plans. No Retry, install, Start, approval or model control was
activated.

## Live process and network evidence

- Exactly **1** listener remained on `127.0.0.1:8765`; non-loopback listeners:
  **0**.
- The observed service tree contained **1** `python.exe` process.
- Visible top-level windows attributable to the service: **0**.
- Prompt Enhancer-owned GPU processes: **0**.
- Local-model runtime state: **idle**; runtime process alive: **false**.

## Still bounded

- Secret/log/database canaries, stale or revoked vault references and exact
  project/chat/client isolation belong to Store-07e.
- Automation did not activate an owner-installed MCP server or manufacture a
  native confirmation. Physical installed-app behavior and one trusted inert
  call remain Acceptance-01 evidence.
- The unavailable live Registry was validated only as a safe failure. A later
  live recovery check must confirm catalogue success when the official source
  is available, without weakening validation.

## Owner click-later ledger

1. Reload `/agent`, open **Agent settings > MCP Store**, and confirm Browse and
   Managed remain navigable at the owner's normal display scale.
2. When the official Registry is available, press **Retry catalog** once and
   confirm tiles appear or another bounded safe error is shown; no lifecycle
   action should occur from browsing.
3. With one explicitly trusted inert reviewed plan, use a fresh native approval
   for Start and one harmless tool call. Confirm the approval preview, timeline
   card and settled receipt identify the same project, host and tool.
4. Try the already-settled approval control again and confirm it refreshes to
   the settled state rather than dispatching a second call.
5. Stop the host and confirm pending calls become unusable, no delayed success
   appears and the model/MCP process leaves no GPU or visible terminal window.

## Next checkpoint

Store-07e is active next: prove that synthetic secret values never reach
ordinary state, logs, database records, API errors or UI; stale vault references
fail closed; and concurrent clients cannot cross project or chat boundaries.
See [Store-07e entry](checkpoint-mcp-store-07e-entry.md).
