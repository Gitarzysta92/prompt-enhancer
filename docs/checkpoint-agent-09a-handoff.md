# Agent checkpoint 09a — deterministic native owner shutdown

Date: 2026-08-28

## Outcome

The separate Agent chat is still one child WebView in the existing Prompt
Enhancer process, but closing the primary Agent window now deterministically
closes that child without a second quit prompt. The local listener and all
runtime workers then complete the same owned cleanup path.

This checkpoint also repairs the previously recorded
`runtime_stop_failed / automation_grant_worker` shutdown. The automation worker
now propagates its stop event through a content-free cooperative cancellation
scope. Provider ingestion, Codex app-server waits, and Claude transcript scans
leave at safe boundaries instead of exceeding the desktop cleanup deadline.

## Defects reproduced before the repair

- Closing the owner while the chat child was open left the child behind with
  its own native quit confirmation. The listener therefore remained alive even
  though the primary window had disappeared.
- Disabling only that child confirmation fixed the orphan, but a real close
  still exposed the historical content-free diagnostic
  `runtime_stop_failed: automation_grant_worker`.
- The worker began a provider refresh immediately and could wait up to ten
  seconds for a local Codex app-server response while its shutdown join allowed
  five seconds. Claude transcript enumeration/parsing also lacked the shared
  cancellation boundary.

## Implemented boundary

- Ordinary child closes retain native confirmation so a draft is not discarded
  accidentally. Owner shutdown disables confirmation only on its already-owned
  child immediately before `destroy()`; no new process, listener, runtime, or
  window can be created during shutdown.
- Added one reusable content-free `raise_if_runtime_cancelled` boundary. It is
  inert outside an explicitly scoped request/worker and remains suppressed
  inside critical cleanup restoration.
- The automation worker scopes each poll to its own stop event.
- Its first poll now waits one normal scheduler interval instead of starting a
  provider refresh in the desktop startup critical path. A quick open/close no
  longer creates local provider work solely to cancel it moments later.
- Ingestion checks cancellation before provider probe, page listing, session
  reads, persistence-derived metric work, and every next session. A cancelled
  started ingestion is settled with the fixed `application_shutdown` code and
  its adapter still closes in `finally`.
- Codex JSONL waits poll cancellation every 50 ms rather than sleeping until the
  provider timeout. A cancelled wait kills only its owned hidden app-server
  helper; the normal adapter close then reaps it and joins the reader.
- Claude transcript directory scans and line parsing check the same scope at
  bounded iteration points.

## Automated verification

- Cancellation, provider, ingestion, transcript, native-window slice:
  **75 passed**.
- Broader desktop lifecycle, single-instance, runtime-liveness, worker,
  provider, ingestion, and native-window slice: **180 passed** with one known
  Starlette/httpx deprecation warning.
- The native child regression asserts ordinary confirmation remains enabled and
  owner shutdown changes it to false before exactly one destroy.
- Adversarial tests prove a blocked automation poll stops within its 500 ms test
  deadline, an empty Codex response queue does not wait for its ten-second
  provider deadline, the owned helper is killed before normal reap, cancelled
  ingestion never reads the adapter and still closes it, and Claude scan/parse
  loops stop under the shared scope.

## Correctness repair during live acceptance

The first close after adding cooperative provider cancellation removed both
Agent windows and the listener, but the old process published the same worker
diagnostic several seconds later. The worker had already begun its first
provider refresh during application startup, creating avoidable cleanup work in
the shortest open/close path. The scheduler now waits its normal 60-second
interval before the first poll. A dedicated regression proves that starting and
stopping inside that quiet interval performs zero provider polls, while the
separate blocked-poll regression still proves cancellation after a poll begins.

## Live Windows acceptance

- Started one hidden/console-free launcher and observed one Agent owner window,
  one listener on `127.0.0.1:8765`, no terminal-like window, and no model
  runtime process.
- Resumed the retained fictional `Synthetic Agent 08s Chat` and opened exactly
  one separate Agent chat child.
- Closed the owner once and confirmed only the owner's native quit prompt.
- Observed the final repaired close for eight seconds after confirmation. Its
  final state remained zero Agent owner windows, zero Agent chat windows, zero
  Prompt Enhancer diagnostic windows, zero terminal-like windows, zero
  listeners on port 8765, and zero known local-model runtime processes.
- No model was loaded, no prompt was sent, and no protected action was approved.

## Privacy boundary

Only the already-created fictional Agent project/chat was selected. No provider
session, provider prompt, credential, account configuration, home-directory
content, or real workspace file was read. Diagnostics and process checks used
only fixed reason codes, exact window titles, listener counts, and model-process
liveness booleans.

## Remaining owner gates

- Connect one intended installed MCP client without changing its provider
  configuration automatically.
- Run one chosen local model through a completed turn and Stop.
- Review one fictional file write/diff and unload the model with exact process
  and CPU/GPU cleanup evidence.
- Perform the final visual preference pass before proposing any legacy-surface
  deletion.

No commit or push was requested for this checkpoint.
