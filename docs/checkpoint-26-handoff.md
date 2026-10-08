# Checkpoint 26 — Agent turn details and verified file-write receipts

Date: 2026-08-26. Status: implemented and bounded verification complete.
Scope: memory-only Agent chat telemetry, reviewed-write
summaries, safe file opening, and the transport/UI defects exposed by verifying
those features. This is a bounded checkpoint, not whole-product certification.

## Changes to review later

1. Expand **Turn N details** below a finished, stopped or failed turn. It shows
   the actual requested model alias, termination reason, server-observed timing,
   runtime-reported usage and tool outcomes. A completed response is explicitly
   not proof that the task succeeded.
2. Missing token counters say **Not reported**, not zero. Partial coverage and
   invalid usage are separate states. A turn total is shown only when every
   model request reported that counter; no request is silently omitted from a
   numeric sum. Genuine reported zero remains zero.
3. **Agent file writes** lists actual reviewed `write_file` receipts, including
   relative paths, created/modified/unchanged status, line additions/removals,
   byte size and verified revision. An attempted write with failed readback
   is marked **Effect unverified**, never promoted from the model's claim.
4. Click a file to open its current content. Main chat uses its existing editor;
   the dedicated window opens the workspace on demand. Focus moves to the
   editor. Declining the discard prompt retains an unsaved manual edit; hiding
   the dedicated workspace uses the same protection and returns focus to chat.
5. Tool outcomes now distinguish completed, failed, not approved, cancelled,
   unverified and legacy unknown results. Command attempts explicitly say that
   their file effects are not inventoried. These entries are individual write
   observations, not a net Git diff or a complete list of external/manual edits.

No native confirmation, workspace boundary, model activation, content retention
or metric-publication permission was broadened. No durable conversation storage
was added. No real model/GPU was used for this checkpoint.

## Evidence and defects repaired

- Fourteen initial turn-detail regressions failed because completed turns had no
  summary. The new builder binds metadata to one admitted turn and captures the
  model alias used by that request, even when the active model later changes.
- Whole and streamed replies reject ambiguous JSON envelopes. Typed invalid
  usage does not discard an otherwise completed answer, but cannot become a
  number. A later valid-looking packet cannot erase earlier invalid usage.
- Real loopback HTTP tests showed that a separate usage trailer was lost after
  the finish chunk. The owned adapter now reads only the expected metadata,
  bounded by 250 ms, 32 lines and 64 KB. Unexpected text/tools are not admitted.
  Generic iterators still stop at their terminal receipt.
- A real Windows stream reproduced Stop waiting for the remote server to close
  its connection. Cross-thread buffered-reader close/shutdown was insufficient.
  The owned HTTP response now uses a nonblocking reader with a 100 ms
  cancellation-check interval. A metadata line dribbled across many reads also obeys one
  absolute deadline. HTTP chunked and content-length framing remain supported.
- Late whole-request HTTP errors and exceptions after Stop are now recorded as
  stopped, rather than failed. The actual socket-read regression completes
  without waiting for EOF. This does not establish cancellation before response
  headers arrive or immediate cancellation of an already-running command.
- Real frontend HTTP testing reproduced a dedicated-window file-open failure
  under React Strict Mode: effect cleanup aborted the first request, while a
  consumed-request marker suppressed the replacement. The marker is now cleared
  with the owned operation. A failing component regression was added first and
  passes after the repair.
- The first HTTP receipt fixture omitted required private SSE headers; the
  application correctly refused it. The fixture was corrected. The private
  header check was not relaxed to pass the test.

## Contracts and interpretation

- Agent session/events: `local-agent.v4`; frontend and backend must be deployed
  together. Reload old pages after restarting the app. Older event versions are
  rejected rather than coerced. The database remains schema 61.
- Turn metadata: `agent-turn.v1`, with one turn ID, closed termination reason,
  server-monotonic timing source and bounded tool accounting.
- Usage: `agent-token-usage.v1`, source `runtime_reported`. Complete-counter
  request coverage is separate from per-field availability. Input/output/total,
  cached-input and reasoning counts are validated for integer bounds and
  coherence. Costs, GPU-only time and token estimates are not invented.
- Writes: `agent-write.v1`, source `reviewed_write_file`; line accounting uses
  `line-sequence-diff.v1`. Only complete verified readback establishes the
  after-revision and effect counts. Refused/stale changes carry no applied-write
  receipt. Paths and hashes are still sensitive metadata, not anonymous data.
- Timing includes approval waits in total duration. Model request time includes
  transport and bounded usage collection. First streamed text may be content or
  an enabled model-provided reasoning fragment; it is not a tokenizer/GPU metric.
- The displayed alias is not a certified immutable model/tokenizer revision.
  Usage is an observation reported by that runtime, not independently measured
  billing or evidence of task success.

The local runtime request uses `stream_options.include_usage`, described in the
[llama.cpp server schema](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/server-schema.cpp).
The tests exercise protocol behavior with fictional servers, not every installed
llama.cpp/model version.

## Verification

Final consolidated results, without adding overlapping earlier reruns:

- 285 backend regression tests across 14 Agent, runtime, lifecycle, API, strict
  model-reply and privacy-boundary files passed. This includes all 14 actual
  HTTP transport cases. The existing test-client deprecation warning remains.
- All 85 synthetic browser checks passed, including 34 populated workflows at
  360 and 1440 px, standalone cards, navigation and accessibility checks.
- All 22 intercepted-HTTP browser cases passed, including receipt parsing and
  file opening through the real frontend transport in main/dedicated views.
- The final full frontend run passed 1,688 tests across 126 files, including the
  added Strict Mode regression. The earlier 1,687-test run is not added to it.
- Production build, generated API consistency, explicit strict TypeScript for
  browser fixtures, Python compilation and whitespace checks passed.
- In-app browser inspection used fictional turn data at narrow and desktop
  widths. It confirmed no page-wide horizontal overflow, expandable details,
  current-file opening and editor focus. No screenshots were saved to the repo.

The full backend tree was not repeated for this checkpoint; checkpoint 25's
full-tree sweep remains historical evidence, including its known privacy failure
and Windows symlink skips. Passing focused tests do not replace those limits.

Reproduction from the repository root, then the frontend directory:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_local_agent.py tests/test_local_agent_completion.py tests/test_local_agent_receipts.py tests/test_local_agent_turn_details.py tests/test_local_agent_usage_transport.py tests/test_local_models.py tests/test_runtime_liveness.py tests/test_desktop_lifecycle.py tests/test_worker_core_lifecycle.py tests/test_openapi_export.py tests/test_privacy_and_config.py tests/test_privacy_binary_state.py tests/test_privacy_scan_exclusions.py tests/test_model_reply.py -q -p no:cacheprovider --tb=line
.venv/Scripts/python.exe scripts/privacy_scan.py
cd frontend
npm test -- --maxWorkers=2 --reporter=dot
npm run test:e2e -- --workers=2 --reporter=line
npm run test:e2e:local -- --workers=2 --reporter=line
npm run build
npm run check:api
```

The scanner command is intentionally still failing on the exact known artifact
below. It is not an omitted or waived acceptance gate.

## Remaining limits and cleanup

- The unchanged privacy scanner still reports exactly one old synthetic SQLite
  artifact under `test-results/browser-workflow-e3rix2kz`. Its automated removal
  was previously blocked. No alternate removal, exclusion or scanner bypass was
  attempted. This blocks privacy sign-off, not independent implementation work.
- Normal owner-app restart, real-model answer/usage quality, native picker and
  approval click-through, and packaged-launcher acceptance are not claimed.
  Production assets are rebuilt; the owner app was not started against private
  configuration or provider content.
- Durable Agent retention, syntax editing/net multi-file diffs, representative
  calibration, immutable model identity, peer delivery reconciliation and the
  existing authorization-gated product decisions remain open in the ledger.
- Final cleanup found zero model-runtime processes and no owned HTTP-test or
  normal owner-app listener. The owned in-app browser tab was closed and its
  viewport restored. The pre-existing loopback synthetic development listener
  was preserved. No commit or push was requested or performed.

Next bounded candidate: cancellation ownership while waiting for initial model
response headers, including truthful pending/closing state. It can be reproduced
with a delayed synthetic HTTP server without reading provider content or loading
a GPU model. It is separate from durable-content retention or aesthetic approval.
