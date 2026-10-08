# Checkpoint 21 — real Agent workflow and shutdown reliability

Status date: 2026-08-26

Status: reproduced repairs implemented and integrated checks executed. Privacy sign-off is blocked on removal of an old disposable synthetic fixture; the overall gate is not green. No commit or push performed. Checkpoints 19 and 20 remain preserved in the working tree.

Continuation: independent development resumed after the cleanup restriction. See **Agent closing recovery** below for the newer bounded repair and its verification; the original integrated baseline is retained as earlier evidence, not relabelled as a new full-backend run.

## What changed

- Desktop startup/shutdown now verifies owned-thread exit, shares exhaustive cleanup with the HTTP lifespan, and reports safe component/reason codes instead of hiding failures or exposing exception details.
- Local inference no longer uses system proxies or follows redirects. Shut-down services reject new model/Agent/evaluation work.
- Agent transcripts remain readable in narrow main and dedicated windows. Redundant empty tool-only completion bubbles are removed; interrupted replies stay visible. Model controls reflect a confirmed disconnection.
- Agent send is failure-atomic if its worker cannot start. Pending approvals are denied during shutdown, and a surviving turn cannot be silently discarded by session deletion.
- Synthetic model-screen jobs own their child process and cancellation. Failed/empty evaluations are not successful results; cancellation and unconfirmed cleanup have explicit UI/API states.
- Active analysis/watch workers cooperate with shutdown, preserve committed results and lease ownership, and do not manufacture model-measurement failures.
- Shared-folder SQLite connections close on every path. This fixes the reproduced Windows temporary-state cleanup failure without changing transaction rollback.

The [verification ledger](goal-verification-ledger-2026-08-26.md) records reproduction, scope, evidence and limitations.

## Original integrated verification baseline

| Gate | Baseline evidence |
| --- | --- |
| Real installed local model | Direct reply, actual Agent/file tool, exact fictional-file answer, stream stop, model unload and retained conversation passed |
| Real HTTP/browser workflow | Selected model started, session/composer became usable, tool/answer appeared, response stopped in 303 ms, unload disabled sending without deleting chat |
| Browser regression | 63 synthetic workflows + 12 intercepted local-contract cases passed; four new narrow transcript geometry cases |
| Agent component | All 47 tests passed. A timing-sensitive approval setup now explicitly awaits fixture promises; rejection/retry assertions remain, with an additional enabled-control check |
| Full frontend | 1,523 tests passed across 122 files, including the final standard-worker run after the test setup correction |
| Full backend | 3,649 passed, 9 skipped, 1 failed: the repository privacy assertion rejects the known synthetic fixture. All 254 test files ran in two non-overlapping shards |
| Windows process-tree preflight | Three cases passed, no skips |
| Native Agent and overlay | Actual isolated hidden windows loaded and closed; listeners and temporary state were released |
| Build / TypeScript / API / Python compile / lock | Passed |
| Privacy / whitespace | Whitespace passed; privacy blocker described below |
| GPU cleanup | Zero `llama-server` processes observed after the real-model checks; unrelated GPU applications were untouched |

Fixture browser tests do not prove real inference, human native approval or peer delivery. The separate real-model workflow covers one installed model, not all models or calibrated quality. No owner sessions, credentials or configuration were read.

Backend shard detail: 1,820 passed / 6 skipped / 1 failed in 19m36s, and 1,829 passed / 3 skipped in 23m44s. The same existing test-client deprecation warning appeared once per process. The nine skips cover database, model provenance/evaluation, quarantined file reading, scanner, social SQLite and home-directory symlink boundaries; this Windows environment cannot create the required links. They remain unverified here, not counted as passes. Focused test runs are not added again to the full-suite total.

The final frontend command was `npm test -- --reporter=dot`; browser commands were `npm run test:e2e` and `npm run test:e2e:local` with separate disposable output directories. Python sources compiled, `uv lock --check --offline` passed, and `npm run build` / `npm run check:api` passed. Backend sharding alternated the sorted `tests/test_*.py` file list; `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q` is the cache-free serial equivalent. All isolated test hosts and native windows were stopped. No restart or readiness claim is made for the owner's normal application instance.

The final scan also detected synthetic privacy-test canaries in the two custom pytest cache `nodeids` files written when the shards ended. Those exact generated index files were removed after path/link validation; they contain no needed application state and can be regenerated. Future custom-shard runs should use `-p no:cacheprovider` instead of creating extra test-ID caches under `test-results`. No scanner rule or test assertion was weakened.

## Cleanup needed before sign-off

The old `test-results/browser-workflow-e3rix2kz` fixture contains only the disposable fictional workspace, stop marker and SQLite state from reproducing the connection leak. The privacy scanner correctly rejects the leftover database. Automated deletion was blocked, and owner removal of that exact directory was requested. Do not weaken the scanner or exclude the artifact. A new fixture using the fixed connection handling already removed itself successfully.

After that exact directory is removed, rerun `.venv/Scripts/python.exe scripts/privacy_scan.py` and `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_privacy_scan.py::test_repository_passes_privacy_scan -q`. A successful rerun is still required before sign-off; the current failure is not relabelled as a pass.

## Review later

1. Agent: select a disposable workspace and model; confirm chat opens with an obvious composer. Send a harmless read request, stop a response, then stop the model. The chat should remain visible until the application exits.
2. Narrow window: inspect the transcript, tool activity and composer in both the main Agent page and its dedicated window.
3. Native-only actions: check folder picking and one reviewed fictional-file change in the real desktop window. An ordinary browser must not gain those permissions.
4. Shutdown/restart: confirm the desktop closes cleanly and can reopen. Record an exact safe failure code if it cannot; the earlier unexplained owner-window exit has not been retrospectively diagnosed.

## What remains

Passing these gates is not a 100% bug-free or product-complete claim. Work that can be scoped without owner ratings includes richer truthful per-turn telemetry, changed-file summaries and further explicit recovery/launcher acceptance cases. These should be individual checkpoints with acceptance tests, not another unbounded redesign.

Agent conversations are still memory-only; durable retention needs the existing content-storage decision. Calibration/usefulness and visual preferences require owner judgment. Native-presence click-through, symlink-capable testing, real peer delivery and the installed OS launcher retain their integration gaps. Production identity/billing, internet collaboration, encrypted retention, remote annotation destinations and signed distribution remain separate requirements or authorization gates. An uncertain remote outcome is still not an authoritative delivery receipt.

## Agent closing recovery — continuation on 2026-08-26

The privacy cleanup restriction does not prohibit independent repairs. With renewed authorization, an exact, validated nonrecursive cleanup was attempted; the execution tool rejected it before launch. No fixture file was deleted and no alternate deletion path or scanner exemption was used.

Reproduced and repaired:

- A session whose turn survives a close request was internally closed to new work but still appeared ready in the UI. `local-agent.v3` now exposes required `closing` state in session and event snapshots. One status event wakes an already-waiting stream; repeated retries do not spam it.
- Closing chats preserve unsent drafts, disable sending, prompt rewriting and session-model activation, hide late model-action approvals, and offer **Retry closing session**. Stale events and stop acknowledgements cannot reopen them. Closing a different session does not disable the active chat.
- The browser transport discarded the close-timeout reason and tried to parse successful HTTP 204 deletion responses as JSON. It now retains only the allowlisted recovery codes and requires the documented no-content receipt for deletion. Unexpected success payloads remain failures. A session already removed in another window can be cleared after HTTP 404 instead of leaving an endless retry card.

Deploy the backend and rebuilt frontend together and reload open pages: v2 event streams intentionally do not satisfy the new v3 contract. No owner application restart is claimed. Model stop/unload remains independent, and manual workspace editing retains its existing native-approval policy.

Current continuation evidence:

- 61 focused backend tests passed across Agent, OpenAPI, desktop lifecycle and runtime liveness; one existing test-client deprecation warning. The full backend baseline above predates this continuation and was not repeated.
- 165 focused frontend/transport/contract tests passed before the final cross-window absence regression; that additional regression failed before repair and passed afterward. The final full frontend run passed **1,536 tests across 122 files** in 87.98 seconds (`npm test -- --reporter=dot`), including all 56 Agent tests. Focused runs are not added again to that total.
- Production build and generated API check passed. Explicit strict TypeScript checks also passed for the changed browser fixture/spec files. This uncovered and corrected older fixture type widening and unchecked optional fixture methods without changing production behavior.
- Four recovery flows were exercised through the in-app browser: main and dedicated views at 360 and 1440 px, disabled chat/model-start controls, timeout feedback, successful retry and no page-wide horizontal overflow. A narrow screenshot was inspected but not saved in the repository. Matching reusable browser cases were added; this is not a new claim that the entire historical browser suite was rerun.
- One broader frontend run exposed a timing-sensitive review-test setup: it acknowledged a receipt before its asynchronous acknowledgement-reset effect completed. The test now awaits that effect before acting; the exact confirmation-enabled and stale-review assertions remain. All 39 tests in that review panel passed afterward. No production approval check was relaxed.
- The unchanged privacy scanner still reports exactly one prohibited artifact: the old synthetic SQLite fixture described above. No private sessions, credentials or owner configuration were used, and no model was loaded for this slice.
- The owned synthetic test server was stopped and its listener was confirmed absent; the browser tab was closed and its viewport restored. A separate process check found zero `llama-server` processes. Whitespace and Python compilation checks passed. No commit or push was performed.

Review later: close an idle disposable Agent session and confirm it disappears without an error; if a running session cannot finish closing immediately, confirm the closing label, preserved draft and explicit retry. Stop/unload any model used for that manual check separately.
