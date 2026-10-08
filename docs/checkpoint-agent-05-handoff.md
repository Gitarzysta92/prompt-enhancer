# Agent-05 handoff: rich chat output, immutable artifacts, and safe viewers

Date: 2026-08-27
Status: implementation and synthetic automated/browser verification complete; native owner reload remains deferred

## Outcome

Durable local Agent chats now expose reviewed workspace outputs as immutable,
versioned artifacts. Text, Markdown, code, image, and PDF outputs have truthful
preview behavior; active or unsupported formats remain download-only. Every
preview and download revalidates the current workspace bytes against the exact
recorded digest and size before returning content.

Agent messages also render safe GitHub-flavoured Markdown, including headings,
lists, task lists, tables, strikethrough, links, and fenced code with explicit
copy controls. Raw HTML, remote Markdown images, unsafe links, and injected DOM
content remain inert or omitted.

## Implemented boundary

- `agent-artifact.v1` records exact project, session, path, immutable version,
  media type, preview class, provenance, source turn/event, digest, byte size,
  timestamps, and truthful availability.
- Agent catalog schema v3 adds append-only artifact/version storage, independent
  revisioning, project/session isolation, bounded counts and bytes, immutable
  version triggers, and session-delete cascade.
- Verified reviewed writes are projected automatically into artifact versions.
  A native-only capture endpoint can admit a separately verified workspace
  output without granting reusable write or command authority.
- Artifact reads pass through the bounded no-follow workspace adapter on every
  request. Missing, changed, malformed, or mismatched bytes become explicit
  `missing`, `stale`, or `malformed` states and are never substituted with the
  current file.
- PNG, GIF, JPEG, and PDF previews require bounded byte-level validation.
  Filename suffixes alone never make binary content previewable. HTML, SVG,
  XML, office formats, and unknown binary data stay download-only.
- Content responses are private and non-cacheable, use no-sniff and no-referrer
  protections, apply a sandboxed CSP, force text to inert `text/plain`, sanitize
  download names, and support only one bounded byte range.
- The Agent UI has session-level artifact cards with distinct kind labels,
  provenance, event lineage, version and size. Its modal viewer revalidates
  before showing inert text, image, or sandboxed PDF content; stale content is
  never fetched. Downloads require an explicit click and report failure without
  changing the workspace.
- The viewer traps Tab/Shift+Tab, closes with Escape or backdrop/Close, restores
  focus to the originating card, revokes object URLs, and becomes a full-height
  mobile surface below the responsive breakpoint.
- Durable retained chats reopen with the same artifact inventory. Live chats
  refresh outputs after settled turns without inventing artifacts when none
  exist.
- `local-agent-orchestration.v3` documents a finite external-controller loop:
  exact project/session identity, one message only while idle, monotonic event
  cursors, no automatic retry after ambiguous submission, native-only approval,
  explicit terminal conditions, recovery revalidation, and artifact lineage.
  It is suitable for a local Codex, Claude, or other controller without exposing
  a raw-transcript MCP surface.
- The native user-presence bridge now recognizes every protected Agent route,
  including recovered authority, create/move/trash/transaction operations and
  artifact capture. It still rejects wrong methods and extra path segments.

## Correctness repairs found during validation

1. The native bridge originally allowed only approvals and one edit-apply path,
   making several advertised protected operations impossible. Exact method/path
   patterns and coverage now exist for every protected Agent action.
2. Missing workspace paths and storage failures did not consistently close into
   artifact-domain errors. They now map to stable, non-leaking failure states.
3. A failed explicit artifact download rejected silently. It now reports an
   actionable in-view error, resets its busy state, and confirms that no
   workspace change occurred.
4. The modal initially handled Escape but did not contain keyboard focus. Tab
   and Shift+Tab now wrap within the active dialog and focus returns on close.
5. Rendered mobile verification found that the high-specificity fixed-backdrop
   rule overrode the mobile zero-padding rule, causing the viewer to extend past
   the viewport. The mobile override now uses the same specificity; the dialog
   and footer end exactly at the viewport boundary.
6. The synthetic retained-history acceptance fixture exported the broad live
   event union rather than the narrower durable allowlist. It now explicitly
   projects only stored-event fields and kinds.
7. The full JSDOM gate exposed resource-starved five-second timeouts and one
   asynchronous focus assertion race. The default worker count is now bounded
   at two and the focus test waits for the actual effect; no assertion or safety
   condition was removed or relaxed.
8. The gated cancellation fixture predates runtime request reservations and
   crashed before reaching its HTTP boundary. It now models reserve/release
   ownership and asserts that every synthetic request is released after cleanup.

## Verification receipts

- The complete frontend gate passed: **1,952 tests across 143 files**.
- The focused artifact/page/contract/transport slice passed **269 tests**;
  the post-fix Agent page and artifact component slice passed **96 tests**.
- The artifact/catalog/history/orchestration/native-presence/OpenAPI backend
  slice passed **44 tests**.
- The broader local Agent, workspace, change-set, cancellation, and transport
  slice passed **349 tests**. Its request-cancellation harness passed **19/19**.
- One intentionally excluded backend case launches a real child command tree to
  prove timeout cleanup. It was not run during this checkpoint to avoid visible
  process surprises; no claim is made for that case in this receipt.
- The production TypeScript/Vite build passed with 519 modules transformed.
- The dev-only acceptance fixture and its Playwright specification pass strict
  standalone TypeScript checking.
- Rendered loopback verification passed at the default desktop viewport and at
  390 x 844. It covered durable project/chat browsing, the artifact card,
  revalidated text preview, modal placement, visible footer, Tab/Shift+Tab,
  Escape, focus restoration, horizontal fit, and browser console warnings/errors.
- `git diff --check` reported only existing Windows line-ending notices and no
  whitespace error.
- The repository-wide privacy scanner has the same known pre-existing blocker:
  untracked binary `docs/checkpoint-agent-02-shell.png`. No Agent-05 code or
  synthetic fixture added another finding; the blocker was not deleted or
  bypassed.
- Zero Prompt Enhancer and zero `llama-server` processes remained after
  validation. Ports 8765 and 8766 were closed. The already-running loopback Vite
  fixture remained on 127.0.0.1:4173; no native app, model, GPU job, Claude CLI,
  or additional server was launched for Agent-05.

## Owner checklist for the later native reload

1. Open a **Save locally** chat in a synthetic workspace and approve creation
   of one Markdown/code file. Confirm an artifact card appears with the reviewed
   path, version, size, and source event.
2. Open the artifact. Confirm exact text is shown inertly, the viewer owns focus,
   Tab wraps, Escape closes it, and focus returns to View.
3. Download that version and compare its digest with the reviewed write receipt.
4. Change the file outside the app, refresh artifacts, and confirm the recorded
   version becomes stale and neither preview nor download returns replacement
   bytes. Repeat after deleting the file to confirm `missing`.
5. Capture one valid synthetic image and one PDF through native confirmation.
   Verify their previews, then test an HTML/SVG/office file and confirm it remains
   download-only.
6. Restart the app and reopen the saved chat. Confirm its artifact inventory and
   version lineage survive while approvals and reusable authority do not.
7. Exercise the documented orchestration manifest with a local controller. Send
   only while idle, advance one monotonic cursor, surface approvals to the native
   owner, and stop only at the documented terminal condition. Do not auto-retry
   an ambiguous message submission.
8. Resize the native window through desktop and narrow widths. Confirm the
   project rail, transcript, artifact cards/viewer, file review, runtime card,
   and composer never overlap.

These native checks are intentionally not marked passed. They require an owner
reload and optional real local-model use, which was avoided after the previously
reported terminal-window cascade.

## Capability-list status and next checkpoint

Agent-05 completes safe rich Markdown/code rendering plus immutable artifact
cards, lineage, preview/download controls, retained-chat integration, and the
finite external-controller protocol. Session output is currently grouped in a
dedicated transcript panel; per-turn inline attachment chips remain an optional
later refinement.

The next correct slice is **Agent-06 — capability-driven multimodal input**:
validated image attachments, bounded audio files and recording, model capability
discovery, composer controls that appear only when supported, local-only preview
and removal, upload/decoding cancellation, and truthful unsupported-state UX.
After that come the runtime-backed context-usage meter, session fork/branch and
export/import semantics, and advanced placement/model-switch acceptance.
