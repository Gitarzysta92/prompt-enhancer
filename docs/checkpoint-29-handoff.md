# Checkpoint 29: approved command Stop, ownership and cleanup truth

Status: scoped implementation and automated verification complete, with the
unchanged one-artifact privacy finding. Final in-app/resource checks are complete
and recorded below. This is not whole-app completion or 100% correctness.

## What changed

- Stop now reaches an already-approved command, including silent commands and
  waits for an occupied command lane. Session deletion and application shutdown
  signal the same owned work. Another command's cancellation event is separate.
- The Windows launcher uses documented atomic Job Object admission, a restricted
  stdio-handle list and kill-on-job-close. Unsupported admission fails before an
  unowned child can execute. A shell exiting does not hide its remaining ordinary
  descendants. Root/job exit, pipe-worker joins and handle releases must agree
  before cleanup is called confirmed.
- Both command pipes are drained during execution. Each retains a bounded
  96,000-byte raw tail, each decoded result is capped, and the combined tool
  message remains at most 24,000 characters. Large output cannot accumulate
  without a limit until timeout. Truncation, partial output and exit status stay
  distinguishable; the Windows UTF-8 output path has a real-process regression.
- Cancellation produces a stopped turn and cancelled command, not a successful
  command or another model step. Earlier effects are not undone, and command
  file effects are explicitly not inventoried.
- Uncertain command cleanup has a fixed `command_cleanup_unconfirmed` reason,
  an unverified tool effect and a failed/incomplete turn. It quarantines the
  Agent service, including other pending approvals, and survives the original
  worker's exit. New Agent work and manual edit mutations are refused; read-only
  inspection remains possible. Shutdown retains the ownership failure.
- Agent v6 makes `cleanup_unconfirmed` required in session/event responses.
  Frontend transport validates every session response, list identities and
  lifecycle coherence. Old/missing authority and exception-message canaries
  cannot silently become a ready session.
- Main and separate Agent views keep the warning across stale ready responses.
  Send, new sessions, close/retry-close and manual apply stay blocked. The model
  Stop control remains separate. The browser review also led to selectable,
  read-only drafts, explicit copy-before-restart guidance and less repeated
  warning text. Ctrl+Enter cannot bypass the pause.

Native per-action confirmation, the existing command/environment scope and
provider ingestion rules were not broadened. No external inference was used.

## Reproductions and tests

- Seven initial command regressions failed before the repair: pre-cancelled
  execution, silent-child cancellation, stdout/stderr bounds, root exit with a
  detached-stdio descendant, turn cancellation propagation and cleanup failure
  becoming successful follow-up chat. All now pass.
- Two additional real Windows setup-release fault cases reproduced cleanup
  being skipped after process creation. They now confirm owned root/job exit
  and attempt all remaining releases. Admission refusal has no unowned fallback.
  Even the intentionally failing tests used exact owned handles for final cleanup.
- The final focused command set covers Stop/delete/shutdown, bounded I/O,
  cancellation while waiting, two-command isolation, first/second pipe-thread
  startup failures, cleanup/query/join/release uncertainty, cross-session pending
  approvals, manual edit refusal and actual application HTTP serialization.
- The consolidated backend selection passed **248 tests across 15 files** in
  **70.26 seconds**. It includes all command checks and the affected Agent,
  runtime cancellation, native-presence, desktop/worker lifecycle and OpenAPI
  tests. There were no skips in this selection. The existing Starlette/httpx
  deprecation warning remains. Earlier focused runs overlap this selection and
  are not added to it.
- The full frontend suite passed **1,739 tests across 128 files** after the
  selectable-draft polish. Strict TypeScript then caught an empty-message state
  sentinel: the existing string state must clear to `""`, not `null`. That
  one-line type correction passes the final build/type gates and **83 Agent
  tests**. This small final correction has focused, not another full-suite,
  verification. These receipts overlap and are not added together.
- The four new synthetic browser cases cover main/separate views at 360 and
  1440 px, truthful Stop, unverified effects, retained selectable drafts, blocked
  Send and stale-state quarantine. Four intercepted-HTTP cases additionally
  exercise the real frontend transport's 409 handling, CSRF request header,
  minimized errors and stale SSE pages.
- Fixture-only corrections were kept separate from product defects: isolated
  Python needs an explicit UTF-8 emitter; a Windows edit must use the file's
  observed line ending; an Agent model alias must match its model inventory;
  the user-facing failed-turn label is “Incomplete”; and the stale-state test
  must await the delivered page, not a nonexistent ready-state refresh button.

### Final integrated receipts

- Full frontend suite: **1,739 passed / 128 files**, 147.34 seconds, followed by
  the one-line state-type correction and the **83-test** recheck described above.
- Full synthetic browser suite: **97 passed / 11 files** in about 1.1 minutes.
  The four cleanup workflows were additionally rechecked after that type fix.
- Full intercepted-HTTP browser suite: **26 passed** in 42.9 seconds, after the
  final type correction. Together the two full browser suites cover **123**
  cases; the repeated focused checks are not added to that count.
- Production build, strict browser TypeScript and whitespace: passed.
- Generated API consistency and Python compilation: passed.
- Privacy scan: **one unchanged finding**, the old synthetic SQLite artifact.
  No new finding, deletion workaround, scanner exclusion or weakened test.
- In-app final main/separate review: passed. Both retained the cleanup warning
  after an acknowledged older ready snapshot; each preserved and selected its
  entire read-only draft while Send stayed disabled. The observed views fit
  their viewport. The owned review tab was closed; viewport settings were not
  changed, and no screenshot was saved to the repository.
- Owned-resource check: zero model-runtime processes and no HTTP test listener
  remained. The pre-existing loopback development listener was preserved. No
  model was loaded, and the normal owner app was not restarted.

## Review later

1. In an approved disposable command, Stop should first say it is stopping and
   become ready only after owned work exits. Stop response does not unload the
   shared model or reverse earlier file effects.
2. An uncertain cleanup must stay visibly paused even if a later update says
   the model is running. Check the unverified command and incomplete turn,
   select/copy the preserved draft, and confirm Send remains blocked.
3. Long output should show its bounded tail and truncation notice. Command
   effects are not a verified file-change inventory.
4. Reload the frontend and backend together for v6. A legacy backend is not
   accepted as evidence that cleanup is safe. These tests did not restart the
   normal owner application.

## Limits and remaining work

- The Windows tests use finite fictional child programs, not a newly loaded
  GPU model, private provider sessions or a live owner workspace. Native desktop
  click-through and installed-model quality remain separate acceptance work.
- The default runner owns normal descendant lifetime; it is not a sandbox for
  hostile commands, OS services or independently delegated processes. POSIX
  process-group behavior and unavailable Windows symlink capabilities are not
  certified by these Windows results. Injected noncooperative runners are not
  forcibly preempted by an event.
- Restart alone is not proof that an unknown old process exited. Unsent drafts
  and conversations are memory-only; copy what is needed before restarting.
  No persistence, shell session retention or net Git-diff inventory was added.
- The broad backend baseline remains historical: checkpoint 28 recorded 4,070
  passes, nine skips and one privacy-artifact failure before its last correction.
  It was not repeated or relabelled as a current all-green whole-app gate.
- The previously blocked cleanup of the old synthetic artifact was not retried
  through another mechanism. Privacy sign-off remains open.
- Existing working-tree work was preserved; no commit or push was performed.
  The original requirements in the [verification ledger](goal-verification-ledger-2026-08-26.md)
  remain open, including native/owner acceptance, richer editing, durable
  retention, representative calibration, immutable model identity and peer
  reconciliation. These passing scoped tests do not erase those gaps.

Next bounded candidate: audit workspace listing/search under Windows reparse
points and read failures using only fictional folders. That is a separate
scope with reproduction first; this checkpoint does not certify those paths.
