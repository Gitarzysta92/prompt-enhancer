# Checkpoint 28: background model control and truthful retry status

Status: scoped implementation and verification complete, with one known privacy
gate failure and platform skips. The broad backend snapshot precedes the final
cancellation/cleanup correction; that correction has separate focused receipts
below. This is not whole-product completion or a claim of universal correctness.

## What changed

- Model subprocess input and output have separate, joined workers. A child
  refusing a large input can no longer hide cancellation or the timeout in a
  blocking Windows pipe write. The output limit is enforced while the child
  runs, not after collecting unlimited output.
- Only the documented exit/status pairs are accepted: exit 0 with completed,
  or exit 2 with failed. Resource-exhaustion receipts still support the bounded
  CPU fallback. Ambiguous, non-finite, invalid-Unicode and excessively nested
  JSON cannot become model results.
- Per-run progress callbacks are released on every exit. A callback failure
  remains an interruption even if a stage adapter catches it. Cancellation
  cannot become a partial receipt, a CPU fallback or a deep-model result.
- Waiting for the shared model lane now renews the watch lease and checks
  cancellation before any source read. Cooperative stops survive the service
  and publication boundaries without becoming ordinary model failures.
- Unconfirmed process/worker cleanup quarantines the runner and service
  instance. Another request is rejected before another source read or model
  stage. The watch records a fixed nonretryable cleanup reason and does not
  automatically retry it.
- A final regression reproduced cleanup uncertainty arriving after cancellation
  had already released the lease. The original claim can now quarantine only
  that same stopped generation. Cancellation receipts and earlier results stay
  sealed, disabled watches stay disabled, and queued/replacement jobs are not
  changed by stale work. A joined worker thread no longer proves clean model
  cleanup; repeated Stop and same-instance restart preserve the failure.
- The API exposes authoritative quarantine metadata and a minimized cleanup
  error. The frontend preserves its safe reason without exposing exception
  text. Legacy absence of quarantine metadata stays unknown, not permission
  to announce an automatic retry. The watch parser now accepts both provider
  families already supported by the backend contract.
- The main card and separate watch window explain paused retries and retain
  Stop. No-result states do not claim to retain a completed snapshot. Browser
  inspection also removed a conflicting “start a run” empty-state hint and
  kept the cleanup warning after stopping the watch: Stop is not proof that
  the model process was released.

## Review later

- [ ] Cancel an analysis waiting for the local model lane. It should not start
  a new model or publish a new result after cancellation.
- [ ] Cancel while a model is working. The attempt should remain cancelled,
  and any earlier sealed snapshot should remain separate and unchanged.
- [ ] If cancellation also encounters uncertain cleanup, the cancellation
  record must remain visible alongside the cleanup warning. A retry must not
  allocate another model in that same service instance.
- [ ] Check the failed/paused state in both the main metrics card and its
  separate window. Read the recovery guidance, verify Stop remains available,
  and check a narrow window for overflow.
- [ ] Stopping a quarantined watch must not dismiss the cleanup warning or
  imply that the runtime is safe to reuse. Inspect the local runtime and
  confirm its model process has stopped before restarting the app and retrying.
- [ ] Check your actual installed model/native setup separately. These new
  tests use fictional fixtures and disposable non-model processes.

The dev-only `workflow-panels.html?panel=model-job-status` fixture, optionally
with `&window=1`, demonstrates the cleanup warning and Stop flow entirely in
memory. It does not deliberately strand a real model, use GPU memory or read
provider sessions. This fixture is excluded from production assets.

Matching frontend and backend versions must be reloaded together. Production
assets have been rebuilt; the normal owner app has not been restarted.

## Verification receipts

- The initial subprocess reproduction failed five of six cases; the initial
  control reproduction failed all eight cases. These were observed failures,
  not an assumption that all background jobs were broken.
- The completed focused subprocess/control/router run passed **83 tests**:
  15 disposable-process I/O tests, 24 control tests and 44 existing chunked
  runner tests. It covers normal replies, live output limits, blocked input,
  timeout/cancellation, thread-start failures, fallback/deep paths, release of
  callbacks, service admission quarantine and real SQLite watch cancellation.
- A separate service/control integration run passed **49 tests**, including
  minimized HTTP failures. These overlap the focused receipt, not additional
  unique tests to add together.
- The last cancellation/cleanup regression initially failed. After repair,
  **16 targeted checks** passed across cancellation, shutdown, Stop-watch,
  retained heads, claim ownership and cleanup; **nine application-lifecycle
  checks** also passed. Expanded retry fixtures were corrected to use the
  explicit refresh action: Enable intentionally does not reset an already
  enabled watch's quarantine. No safety assertion was removed.
- The expanded intermediate run had **205 passes and three failures** from
  those Enable-versus-refresh fixture mistakes. The 16-check corrective run
  includes all three corrected cases. The final consolidated source run passed
  **162 tests** in 75.25 seconds across control, subprocess I/O, chunked runners,
  service/HTTP, worker lifecycle, desktop lifecycle and OpenAPI. These are
  overlapping verification runs, not counts to add together. The existing
  Starlette/httpx deprecation warning remains.
- The broad backend run completed with **4,070 passed, nine skipped and one
  failed** in 2,121.06 seconds. The sole failure is the repository privacy-scan
  assertion described below. All nine skips are unavailable Windows symlink
  capabilities. This run collected 4,080 tests before the final cleanup-race
  regression/correction; it is not a final-source all-green receipt.
- Main/separate-window cleanup cases passed at **360 and 1440 px**. The full
  synthetic browser suite passed **93 tests**.
- The first full frontend run had **1,710 passes and one timeout** in an
  unchanged team-analytics test. That file passed on the focused recheck; the
  next full run passed **1,711 tests across 127 files**. After adding the
  fixed-reason transport assertion, the final source snapshot passed
  **1,712 tests across 127 files** in 147.03 seconds. No team-analytics code or
  timeout threshold was changed to obtain that result.
- Strict browser-fixture TypeScript and the production build pass. The type
  gate caught a missing safe-error allowlist entry; it was added with a
  transport regression that must retain the fixed code and discard a canary
  exception message.
- The intercepted-HTTP browser suite passed **22 tests** in 22.7 seconds;
  together with the synthetic suite this is **115 browser checks**, not real
  provider or native acceptance. Final generated-API, strict browser-fixture
  TypeScript, Python compilation and whitespace checks passed.
- The privacy scanner still reports exactly **one** prohibited repository
  artifact: the already-known synthetic SQLite file. No new finding or scanner
  bypass was introduced. A separate privacy test run passed 18 cases and failed
  only the same repository-artifact assertion. No all-green gate is claimed.

## Limits and safety

- No real model was loaded for this checkpoint. No real provider session,
  credential or owner configuration was read. No screenshot was saved to the
  repository, and no commit or push was requested or performed.
- Final resource check found zero model-runtime processes and no owned test
  listener. The pre-existing loopback development listener was preserved. The
  owned in-app review tab was closed and its viewport reset. This does not
  measure other applications' GPU memory or restart the normal owner app.
- Process-tree termination relies on platform helpers. These tests do not
  establish every orphan-descendant or inherited-handle behavior. Unconfirmed
  cleanup is a fatal ownership failure, not an accepted model result or an
  automatic retry. Restart alone is not evidence that an unknown old process
  has exited.
- Cancellation remains cooperative at the job/adapter boundary. The default
  subprocess runner checks it while doing I/O; an injected noncooperative
  executor is not magically preemptible. This is not a hard response-time SLA
  or interruption of an already-approved Agent shell command.
- The existing one-artifact privacy finding remains a separate sign-off gap.
  Its previously blocked removal was not retried by another mechanism, and no
  scanner exclusion or weakened test was introduced.
- Original requirements remain in the whole-application verification ledger:
  native acceptance, owner design review, richer editing, durable retention,
  representative calibration, immutable model identity, remote-delivery
  reconciliation and authorization-gated product decisions are not completed
  by this checkpoint.

Next bounded candidate: inspect cancellation and cleanup of already-approved
Agent commands with fictional subprocesses. It must preserve native approval
boundaries and must not claim a command stopped before its owned process exits.
The read-only next-slice audit found that the current command wrapper waits in
`communicate` until its command timeout, clips captured output only afterward,
and does not return positive process-tree cleanup confirmation. Those are
targets for reproduction, not repairs or acceptance evidence in this checkpoint.
