# Checkpoint 27: request-owned cancellation and responsive model chat

Status: implemented and bounded verification complete. This is not an assertion
that the whole application is finished or universally bug-free.

## What changed

- Agent Stop now reaches its owned HTTP request before response headers arrive,
  as well as during partial headers, streamed reads, whole JSON replies and
  error-body reads. Connect and upload waits also observe cancellation. No
  helper worker is abandoned to make Stop appear successful.
- Each turn/request has its own content-free cancellation event. Stopping one
  conversation does not stop a second conversation using the same model and
  does not unload that shared model. Normal response cleanup cannot cancel the
  next tool step or the next turn.
- All three Models chat URLs run blocking runtime I/O away from the API event
  loop. One disconnect watcher owns the request from connect through streaming;
  closing the client or cancelling the ASGI task releases and joins upstream
  work. Ordinary upstream errors retain their actual sanitized HTTP status.
- Agent contract `local-agent.v5` adds explicit `stopping` state to session
  views and event pages. Stop publishes one state change; repeated Stop calls
  do not republish it. A noncooperative injected adapter stays visibly running
  and stopping until its operation actually ends.
- The UI disables repeated Stop requests, preserves drafts, recognizes Stop
  from another window, cancels detached acknowledgment requests, and rejects
  older acknowledgments/event-page state that would rewind a newer turn.
- Browser inspection also corrected a misleading model label: a loaded model
  now says the response is in progress or stopping, not that this busy session
  is ready for another message.

The frontend and backend must be reloaded together for the v5 contract.
Production assets were rebuilt. The normal owner app was **not** restarted;
no owner configuration, real provider content or credentials were read.

## Review later

- [ ] Send a request, then Stop before any answer appears. See “Stopping
  response,” a disabled Stop button and no premature Send control.
- [ ] When the operation ends, see the stopped turn receipt and an enabled
  composer. Missing usage stays “Usage not reported,” not zero tokens.
- [ ] Send another message successfully. The model should remain loaded until
  you explicitly use Stop model.
- [ ] Check the main Agent card and its separate window, including a narrow
  window. The status, composer and controls should stay within the page width.
- [ ] Check the intended native picker/approval flows and your installed model
  separately; synthetic transport tests do not certify those integrations.

The dev-only `workflow-panels.html?panel=agent-stopping` fixture, with optional
`&window=1`, demonstrates the pending state using an explicit fictional gate.
“Finish cancelled example request” releases that test gate. It is not a real
model, an inference-speed demonstration or an owner-data workflow.

## Verification

- The initial real-loopback reproductions failed in all 13 cases: Agent header
  and body cancellation, API responsiveness at every chat URL, and disconnect
  cleanup. A further ASGI-cancellation test reproduced a false 502 before its
  cancellation/error distinction was corrected.
- Final consolidated backend run: **312 passed across 16 selected files**
  (79.15 seconds). This includes 27 new cancellation tests and the existing
  Agent, model, runtime-lifecycle, receipt, API and privacy-boundary regressions.
  One existing Starlette/httpx deprecation warning remains.
- Full frontend suite: **1,693 passed across 126 files**. The final readiness
  wording and its assertions were subsequently rechecked in the **195-test**
  Agent/contract/HTTP group; these are repeats, not additional unique tests.
- **89 synthetic browser checks and 22 intercepted-HTTP browser checks passed**.
  The four new main/separate-window cancellation cases at 360/1440 px were
  repeated after the final wording adjustment and passed. An initial browser
  assertion used the wrong existing usage label; the assertion was corrected
  to the actual truthful label without changing usage semantics.
- Production build, API export/generated-type consistency, strict TypeScript
  for the browser fixtures, Python compilation and whitespace checks passed.
- In-app browser review used only fictional data, checked the disabled Stop
  state and recovery into the next message, and found no horizontal overflow
  at narrow or desktop widths. No screenshots were saved to the repository.

Reproduction from the repository root, then the frontend directory:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_local_agent.py tests/test_local_agent_completion.py tests/test_local_agent_receipts.py tests/test_local_agent_turn_details.py tests/test_local_agent_usage_transport.py tests/test_runtime_request_cancellation.py tests/test_runtime_cancellation_unit.py tests/test_local_models.py tests/test_runtime_liveness.py tests/test_desktop_lifecycle.py tests/test_worker_core_lifecycle.py tests/test_openapi_export.py tests/test_privacy_and_config.py tests/test_privacy_binary_state.py tests/test_privacy_scan_exclusions.py tests/test_model_reply.py -q -p no:cacheprovider --tb=line
.venv/Scripts/python.exe scripts/privacy_scan.py
cd frontend
npm test -- --maxWorkers=2 --reporter=dot
npm run test:e2e -- --workers=2 --reporter=dot
npm run test:e2e:local -- --workers=2 --reporter=dot
npm run build
npm run check:api
```

## Limits and cleanup

- The unchanged privacy scan still fails on exactly one old synthetic SQLite
  artifact under `test-results/browser-workflow-e3rix2kz`. Its removal was
  previously blocked; no alternate removal or scanner bypass was attempted.
  Privacy sign-off remains open, separately from this completed repair.
- The full backend tree was not rerun here. Checkpoint 25 remains the historical
  full-tree receipt, including its known privacy failure and platform skips.
- The tests prove owned-client cancellation and connection closure, not every
  installed runtime's internal generation-abort behavior. Connect/upload fault
  cases use controlled socket doubles; response and disconnect cases use real
  loopback HTTP. Cancellation is not a runtime unload or a hard latency SLA.
- This does not implement in-flight command interruption, durable Agent
  retention, net multi-file editing, representative calibration, immutable
  model identity, peer-delivery reconciliation or authorization-gated product
  decisions. Those requirements remain in the whole-application ledger.
- No GPU model was loaded. Cleanup found zero model-runtime processes and no
  owned HTTP-test or normal-app listener. The existing loopback synthetic dev
  listener was preserved. The owned browser tab was closed and its viewport
  restored. No commit or push was performed.

Next bounded candidate: audit cancellation and timeout ownership in background
inference jobs, with fictional blocked adapters and honest job-state receipts.
That is a candidate for reproduction, not a claim that those paths are already
broken or verified.
