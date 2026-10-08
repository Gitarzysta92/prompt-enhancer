# Runtime checkpoint 01c handoff

## Outcome

Local-model acquisition is now restart-safe and explicitly controllable. A
verified immutable artifact is admitted only when storage capacity is known and
the file plus a conservative reserve fits. Every transfer has a durable state,
attempt, command revision, byte receipt, provenance, partial-retention truth and
cleanup result. The Models page exposes Pause, Resume, Retry and Cancel only for
coherent states and refreshes instead of pretending a stale command succeeded.

Runtime failures now distinguish an ordinary crash from the exact Windows
out-of-memory exit codes. Production model processes are created under owned
process-tree control without visible consoles, inherit only an allowlisted
environment, and are not reported stopped until root, descendants and ownership
handles are closed.

## Changed

- Added a strict versioned download ledger with atomic persistence and startup
  reconciliation. Active transfers become interrupted after an unclean stop;
  paused and failed partials are reconciled from the exact managed partial file.
- Added disk-space admission, deterministic managed paths, immutable
  repository/revision/digest binding, compatible-adapter gating, resumable
  transfer offsets and final atomic publication.
- Added optimistic command routes for pause, resume, retry and cancel. Byte
  progress is monotonic but does not invalidate a user's command revision while
  chunks arrive.
- Cancellation removes only the exact app-owned partial and reports success only
  after cleanup is confirmed. Retry revalidates provenance before network work.
- Shutdown cooperatively pauses active transfers, joins workers within a bound
  and leaves recoverable state for the next start.
- Added exact crash/OOM classification, environment minimization and atomic
  Windows job ownership for production runtime processes.
- Expanded the Models UI with storage evidence, durable recovery alerts,
  accessible progress, state-specific recovery controls and closed failure copy.
- Regenerated the OpenAPI document and TypeScript client.
- Repaired one pre-existing Agent test race so it waits for the visible retained
  history readiness transition instead of assuming a started request is ready.

## Validated

- Focused acquisition/runtime/Windows ownership matrix: **131 passed, 1
  platform symlink test skipped**.
- Focused Models and HTTP transport UI matrix: **224 passed**.
- OpenAPI export suite: **6 passed**; generated-client drift check passed.
- Full backend suite: **4,906 passed, 9 Windows symlink tests skipped**.
- Full frontend suite using the CI command: **171 files, 2,395 tests passed**.
  The complete Agent page also passed independently: **144 tests passed**.
- Python compile check, repository privacy scan and diff whitespace check passed.
- Production TypeScript/Vite build passed with **560 transformed modules**. The
  existing large Agent/PDF chunk warning remains performance debt.

## Live protected-app QA

The previously running native app did not confirm the requested graceful close.
After proving that its exact listener owner had zero model processes and only
embedded browser descendants, that exact process was stopped and one
hidden-console replacement was started. This was a bounded restart, not a broad
process kill.

The protected loopback app served the newly built asset. The Models route
rendered its heading, hardware and storage surfaces, left the loading state,
showed no model-list or ledger failure, and produced no new browser console
errors. No transfer existed, so no recovery control was clicked. The final
process census found exactly one loopback listener, one native app owner, only
embedded browser descendants, zero terminal descendants and zero model
processes.

## Still locked

- No real Hub download, provider credential, private repository or network
  transfer was used. All transfer validation used synthetic public identities
  and offline fixtures.
- No model was loaded and no accelerator memory was allocated. Real CPU,
  GPU/split placement, OOM, switching and memory-release evidence still require
  an owner-approved disposable model run.
- The live empty-download state cannot prove physical pause/resume/cancel button
  interaction; those states have automated DOM and service coverage.
- The native app's current-build graceful close/reopen path remains part of the
  final packaging/release acceptance. The rebuilt app is intentionally left
  running for review.
- Persistent MCP hosting remains separately frozen at Store-06b pending its
  explicit owner gate.

## Click later

1. Open **Models** and confirm the Hardware cards, storage location and remote
   artifact capacity message are readable before any Download action is enabled.
2. With a disposable public artifact, start one transfer, then Pause and Resume;
   confirm the same row and byte progress survive the transition.
3. Cancel a disposable transfer and confirm its row reaches Cancelled only after
   cleanup; restart the app once while paused and confirm it remains recoverable.
4. With a disposable model that fits the admission estimate, start and stop it;
   confirm no console window appears and the UI reports a crash or OOM distinctly
   if the runtime actually exits that way.
5. After unload, confirm the model process is gone and accelerator memory returns
   before switching to another model.

## Next

Runtime-01 automated implementation is complete through this slice. The next
model-lifecycle step is a bounded owner-approved Runtime-01d acceptance run with
one disposable public model and before/after process and accelerator evidence.
Unrelated implementation can proceed to Workspace-01a while that physical
acceptance remains recorded as pending.
