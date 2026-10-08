# Checkpoint 19 — application-wide reliability sweep

Status date: 2026-08-26

Status: 18 confirmed repair groups implemented and regression-verified; frontend/browser/build/API/privacy gates passed; the full backend run passed with nine platform skips. Owner visual approval and production-completeness claims are deliberately separate.

## What improved

- Models and chat: late streams cannot resurrect a cleared conversation; Stop works immediately; failed replies can be retried without losing the next draft; stopped models retain conversation history and cannot silently redirect a message. Repository lookup results belong to the current input.
- Agent: checkpoint 18's single-action model-to-chat flow is retained and now exercised at desktop and narrow widths, through reply/reasoning display and model deactivation. Native-only controls remain honestly gated.
- Team folders: missing actions are disabled, failed refreshes retain acknowledged changes and one-time tokens, and overlapping refresh/actions recover without getting stuck or repeating a transfer.
- Calibration and prompt check: saves keep their acknowledgment, uncertain saves require a status refresh, unavailable actions are disabled, history can be retried, unknown metric values stay unknown, and populated prompt results fit narrow screens.
- Evidence: action reviews can retry, close without accepting, and reopen the same file. Generic previews expire visibly, partial or duplicate proposal lists are rejected, and inconsistent native-capability responses cannot enable acceptance. Successful analysis leaves a workspace receipt.
- Sessions, jobs and automation: partial catalogs are labelled and can load another bounded page; invalid durations are not shown as zero; cancellations stay attached to the selected job; consent names the correct provider.
- Research/model judgments: late judgments, explanations and model-link annotations cannot move between sessions. Benchmark status has an explicit same-job retry; a failed status read is not reported as a failed benchmark. Cancel wait does not claim to stop the model worker.

The detailed UI-00 through UI-20 matrix, SW-01 through SW-18 regressions, rejected audit findings and limitations are in [the sweep ledger](app-completion-sweep-2026-08-26.md).

## Verification

| Gate | Result |
| --- | --- |
| Complete frontend | 1,460 tests passed across 122 files; 89 additional tests versus checkpoint 18 |
| Synthetic browser | 59 passed, including eight new populated workflow cases at 360 and 1440 px |
| Local HTTP contract browser | 8 passed, with every API response intercepted using fictional fixtures |
| TypeScript and production build | Passed; dev-only workflow fixture also type-checked separately |
| Generated API contract | Passed; generated client matches the API schema |
| Privacy/secret scan and whitespace | Passed, including the completed repair documentation |
| Complete backend | 3,608 passed; 9 skipped because Windows symlink creation is unavailable; 1 dependency deprecation warning |
| Running app | Protected Agent launched directly; loopback health and latest built asset verified |
| Test-model cleanup | No model activated by this sweep; zero `llama-server` processes observed |

Six bounded Opus 5 audits and reviewed implementation patches contributed to this batch. Opus findings were reproduced before acceptance; incorrect recommendations were rejected. All model replies/excerpts in tests are fictional. No real provider history, account configuration or transcripts were inspected or sent to Opus.

The browser/API fixtures establish interface and contract behavior, not real model usefulness, actual GPU inference, remote transfer, or native confirmation end-to-end. Other GPU applications were not stopped; zero model runtimes is not a claim that all VRAM is unused.

The nine skipped backend tests cover symlink boundaries and must also run on a symlink-capable host. They were not bypassed or counted as passes. The warning concerns the test client's deprecated `httpx` integration; dependencies were not changed as part of this UI repair batch.

## Ready for owner review

Open [the Agent page](http://127.0.0.1:8765/agent). Keep the protected desktop Agent window open: it owns the service and in-memory sessions. Browse and protected actions require that native window; an ordinary browser remains read-only for those actions.

When convenient, check these in order:

1. Agent: choose an existing workspace and installed model, open chat once, and confirm the message box is focused. Send one harmless request. Stop the model and confirm the conversation remains visible while sending is disabled.
2. Models: send a message, start a new conversation during a reply, and verify no old output returns. Confirm a failed reply can be retried without deleting a newly typed draft.
3. Calibration and prompt check: save a rating and see its confirmation; check a fictional prompt and inspect the result on a narrow window. Generated suggestions must remain visibly distinct from metrics.
4. Evidence: open and close a review without accepting; select the same file again; verify incomplete/expired evidence cannot be accepted. Confirm completed analysis leaves a visible receipt in the workspace.
5. Catalog/jobs: verify partial-list notices, explicit next-page loading, and cancellation feedback on the job being acted on.

These checks are a review checklist, not an instruction to share any private content. Keep screenshots and real evidence out of the public repository.

## Still not certified complete

- Card-by-card visual preferences and live model quality need owner review.
- Agent conversations remain memory-only; durable chats, per-turn timing/token telemetry and richer changed-file summaries remain separate work.
- The earlier native shutdown diagnostic remains open. The first packaged-launcher attempt in this sweep did not leave a listener; a direct entry-point launch succeeded. Its cause was not established, so the packaged launcher needs a separate recheck, not an unsupported claim of a code fix.
- Real native folder picking, confirmation dialogs, filesystem edits and real peer transfers were not repeated against owner data in this sweep.
- Symlink-boundary tests need verification on a host that permits creating symlinks.
- Model calibration/product activation, hosted identity/billing, cross-machine publication, remote annotation and encrypted content retention retain their explicit validation/authorization gates.

Next work should start from one recorded owner finding or one named unfinished feature, with a bounded acceptance test and checkpoint. Do not restart another open-ended all-card redesign or mark every feature complete merely because this test suite passes.
