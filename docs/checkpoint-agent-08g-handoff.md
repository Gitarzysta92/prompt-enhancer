# Agent checkpoint 08g handoff: one-owner separate chat window

Date: 2026-08-27
State: implementation and automated evidence complete; native owner acceptance pending

## Outcome

Agent-08g completes the last implementation group in the frozen Agent legacy-
parity ledger. **Open separate window** now creates or focuses one Agent chat
child inside the existing native process and GUI loop. It does not start a
second listener, application server, command worker, model owner, cleanup path,
or terminal process.

The dedicated window is no longer a chat-only fragment. It carries the full
project/chat rail, durable and metadata-only history navigation, the shared
model/placement/context control, the conversation and composer, and the on-
demand Files & review drawer. The same shell is exercised at 360 px and 1440 px.

This checkpoint did not launch the native application, a local model, an
inference process, a command, or a GPU workload.

## Native ownership contract

- The primary `prompt-enhancer-agent` window remains the only application,
  loopback-listener, native-presence, runtime, command-tree, and shutdown owner.
- A locked coordinator admits at most one child. The first valid request creates
  it; concurrent and repeated requests focus it. Closing it releases the slot so
  one replacement may be created later.
- Primary shutdown destroys the child once before the existing application
  cleanup. Child close never stops the primary server or runtime.
- The native bridge accepts exactly `{version, window_key}` and returns an exact
  content-free receipt. Its `listener_started`, `worker_started`,
  `process_spawned`, and `runtime_owner_created` fields are always false.
- The child route is exactly `/agent/window?window=<32 lowercase hex>`. Extra,
  repeated, malformed, legacy-session, fragment, and cross-route requests fail
  closed.
- The selected session identifier never enters the child URL or Python/native
  bridge. A strict same-origin, memory-only rendezvous channel transfers the
  selection and acknowledges it. Duplicate messages are idempotent.
- Browser fallback reuses one fixed popup name and the same opaque route. If the
  channel is unavailable, the app says selection is unconfirmed and the person
  can choose the chat from the visible Projects rail.
- Native focus is never invented: an unconfirmed foreground attempt is returned
  and shown as `focus_unconfirmed`.

## Defects found during validation

1. The closed **New chat setup** disclosure retained its entire form in the DOM,
   causing duplicate controls and unnecessary hidden UI. The form is now mounted
   only while setup is open.
2. In the dedicated window, the original live-session target could reassert
   itself after selecting a durable unavailable chat. The child now updates its
   target for live navigation and explicitly releases it for retained or
   metadata-only history, so the requested history card remains visible.
3. The catalog compatibility fallback ignored its disabled state on **New
   chat**. Cleanup quarantine and local-app disconnection now disable that entry
   directly in both main and dedicated windows.

Each defect has component and/or real-browser regression coverage.

## Verification receipts

- Native/desktop lifecycle and Windows distribution gate: **203 passed**.
- Complete frontend unit/component gate: **2,045 passed across 153 files**.
- Focused main/dedicated Agent shell browser gate: **4 passed** at 360 px and
  1,440 px.
- Complete synthetic browser gate: **117 passed**.
- Production TypeScript/Vite build: **533 modules transformed**.
- Generated OpenAPI/TypeScript parity: passed.
- Python package/test compilation: passed.
- `git diff --check`: passed; only repository-wide Windows LF/CRLF notices were
  emitted.
- Privacy scanner: exactly one known pre-existing finding,
  `docs/checkpoint-agent-02-shell.png` (untracked binary). Agent-08g adds no
  privacy finding; the file was not changed, removed, staged, ignored, or
  allowlisted.

All fixtures use fictional identities, paths, sessions, models, and content.

## Deliberate limits

- One separate child is supported, not an unbounded set of independent native
  windows.
- Automated pywebview fakes prove ownership and event behavior, not real Windows
  foreground focus, WebView rendering, or GPU cleanup.
- The compatibility route `/agent/window/{session_id}` remains available to old
  browser links and tests, but the native coordinator never uses it.
- Legacy Agent/model-chat removal remains prohibited until the guarded native
  owner acceptance is recorded.

## Owner review later

Run this once, only when ready to observe the machine:

1. Start Prompt Enhancer normally and confirm no terminal-window cascade and one
   owned loopback listener.
2. Open a durable Agent chat, click **Open separate window** several times, and
   confirm exactly one child opens and later clicks focus it.
3. In that child, browse a live chat, a retained chat, and a metadata-only chat;
   confirm the project rail, model/context card, composer, and Files & review
   remain usable with no horizontal overflow.
4. Load one chosen model through the normal control, send one bounded fictional
   request, observe streaming/reasoning or tool activity as supported, then use
   **Stop**.
5. Close only the child and confirm the primary Agent remains usable. Reopen the
   child once.
6. Unload the model, close the primary owner, and verify process exit plus CPU
   `not_required` or measured GPU-memory cleanup.
7. Complete **Connections & controller API → Owner acceptance → Check current
   evidence** and retain only its content-free receipt.

If any cleanup is unknown or failed, do not load another model and do not mark
the gate complete.

## Next bounded slice

No capability implementation slice remains in the frozen sixteen-item ledger.
The next step is the guarded owner acceptance above. After it passes, perform a
separate legacy-surface usage audit and propose any deletion as an independently
reviewed change.
