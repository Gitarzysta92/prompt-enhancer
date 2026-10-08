# Agent-04 handoff: durable local Agent history and restart recovery

Date: 2026-08-27
Status: implementation and synthetic automated/browser verification complete; native owner reload remains deferred

## Outcome

Chats can now be created with an explicit retention choice:

- **Save locally** retains a bounded, append-only conversation and settled
  activity journal in the authored Agent database.
- **Metadata only** retains navigation metadata but deliberately does not retain
  conversation content.

A saved chat can be reopened after a service restart, inspected without making
it live, exported as bounded JSON, and resumed with every protected capability
off. Resume never restores a pending approval, approval decision, runtime lease,
command authority, web authority, or proof that a model is still running.
Writes, commands, or web fetches become available only after a separate native
user-presence confirmation revalidates the exact workspace and the owner-selected
capabilities.

## Implemented boundary

- The authored Agent catalog is now `agent-catalog.v2`; durable event snapshots
  and exports use `agent-history.v1` while live Agent responses remain
  `local-agent.v8`.
- SQLite schema v2 adds an append-only journal with independent optimistic
  history revisions, exact project/session binding, deterministic ordering,
  bounded pagination, a 4,000-event ceiling, and session-delete cascade.
- The durable allowlist admits visible user and settled assistant messages,
  model-provided reasoning, bounded tool identity, terminal tool state,
  reviewed write receipts, fixed status/error events, and settled turn receipts.
- Assistant stream deltas are compacted into settled output. Approval-required
  and approval-resolved events are never stored. Raw tool arguments, raw tool
  output, fetch content, command output, approval IDs, decisions, previews,
  reusable authority, leases, and active-process state are excluded.
- History writes are write-through. An optimistic-revision conflict, invalid
  event, or storage failure marks the live chat failed-closed instead of
  continuing while pretending that retention is healthy.
- Restart recovery reconstructs only visible model history and settled receipts.
  A nonterminal final turn is labelled interrupted; it is not invented as a
  success and is not silently replayed.
- Resume requires the expected catalog and history revisions. Cross-project
  access, archived sessions, metadata-only sessions, stale writers, and corrupt
  stored profiles fail closed.
- Retained-history, resume, export, and native revalidation routes are private
  loopback operations. Sensitive responses carry `Cache-Control: no-store,
  private` and `Pragma: no-cache`.
- The frontend has a strict retained-history parser, paginated retained view,
  Save locally / Metadata only choice, truthful interrupted state, Resume,
  Export JSON, recovery banner, protected-action revalidation, and explicit
  history-storage failure state.

## Restart truth after Agent-04

| Item | Restart behavior |
| --- | --- |
| Project and chat navigation | Durable |
| Save-locally user/assistant messages | Durable and reopenable |
| Settled model-provided reasoning | Durable when visibly returned |
| Settled bounded tool/write/turn receipts | Durable |
| Streaming fragments | Not replayed; only settled output is retained |
| In-flight final turn | Marked interrupted, never successful by inference |
| Pending approval and approval decision | Never restored |
| Raw tool arguments or output | Never stored in retained history |
| Write/command/web authority | Restored off; native revalidation required |
| Model process/runtime lease | Never restored or claimed ready from history |
| Metadata-only conversation | Unavailable by design; no empty history invented |

## Correctness repairs found during validation

1. The HTTP client for recovered-authority revalidation did not attach the
   native user-presence proof. The transport now requires that proof and also
   enforces private no-store response headers.
2. Resume accepted a structurally valid response without checking that its
   returned project matched the requested project. The transport now rejects
   that cross-project mismatch.
3. At short desktop heights the projects/chat rail could collapse to roughly
   one header row while its session entries overflowed into New chat setup. The
   side scroller now uses max-content rows, and the responsive browser test
   asserts that the two cards never overlap.
4. An independently resolving model-catalog refresh could overwrite a model,
   placement, or context selection before Apply. Pending runtime selections are
   now retained until apply or chat change, with a dedicated race test. This
   also repairs an interaction reported during the earlier Agent review.

## Verification receipts

- 1,933 frontend tests across 140 files passed in the complete Vitest run.
- 97 focused Agent page and runtime-control tests passed, including the new
  pending-selection/catalog-refresh race.
- 59 selected Python tests passed across retained history, the Agent catalog,
  orchestration, local Agent behavior, and OpenAPI export.
- Seven dedicated history tests cover restart recovery, API headers, export
  redaction, interrupted turns, stale writers, metadata-only truth,
  cross-project isolation, and dependency-gated authority revalidation.
- Strict history/transport tests cover malformed or extra fields, wrong
  identity/revision/order, forbidden approval/delta/raw-output material,
  no-store enforcement, native confirmation, and cross-project responses.
- Four responsive Chromium acceptance runs passed at 360 px and 1,440 px:
  durable chat browsing/model switching and saved-history reopen/resume with
  protected actions off. A separate 1,280 x 720 synthetic visual pass confirmed
  that the rail no longer overlaps setup and the recovery controls stay inside
  the viewport.
- The production TypeScript/Vite build passed.
- `git diff --check` reported only the repository's existing Windows line-ending
  notices and no whitespace error.
- Zero `llama-server` processes and zero listeners on port 8765 were present
  after validation. The already-running loopback Vite fixture remained on
  127.0.0.1:4173; no Prompt Enhancer server, native window, model, or GPU job was
  launched for this checkpoint.
- The repository-wide privacy scanner has one known pre-existing blocker:
  untracked binary `docs/checkpoint-agent-02-shell.png`. No Agent-04 code or
  synthetic fixture added another finding, and the blocker was not deleted or
  bypassed.

## Owner checklist for the later native reload

1. Create one **Save locally** chat and one **Metadata only** chat in a synthetic
   workspace. Send a few text turns and perform only deliberately reviewed
   synthetic actions.
2. Close and restart the app. Confirm both navigation entries remain, but only
   the saved chat exposes retained messages and Resume.
3. Confirm the saved transcript reports any interrupted turn truthfully and
   does not show a pending approval or claim a model/runtime is restored.
4. Resume the saved chat. Verify File writes, Commands, and Web fetches all start
   off and cannot be enabled without native confirmation.
5. Revalidate only File writes. Confirm writes become available while Commands
   and Web remain off, then repeat with another exact selection.
6. Export the saved chat and verify it contains the visible settled history but
   no approval ID/decision, raw tool arguments/output, fetch content, reusable
   authority, or runtime lease.
7. Create a second project and confirm neither its UI nor direct API navigation
   can read or resume the first project's chat.
8. Resize the native window and verify the project rail, New chat setup, runtime
   card, recovery banner, transcript scroller, and composer do not overlap.

These native checks are intentionally not marked passed. They require an owner
reload and optional real local-model use, which was avoided after the previously
reported terminal-window cascade.

## Capability-list status and next checkpoint

Agent-04 completes durable authored chat history, restart reopening, local
export, interrupted-state truth, and authority-safe resume. Project/chat
create, browse, rename, search, pin, archive, restore, and hierarchy were already
delivered by Agent-01/02; Agent-04 makes retained chats genuinely reopenable.

The next correct slice is **Agent-05 — Artifact cards and safe viewers**:
immutable artifact/version lineage; truthful provenance and stale/missing
states; transcript cards for text, diff, test, report, image, and document
outputs; authenticated no-store byte/range access; inert text/image previews;
and a sandboxed, no-network PDF viewer. Rich Markdown and code-block rendering
should be delivered as the transcript foundation of that same checkpoint before
artifact cards depend on it.
