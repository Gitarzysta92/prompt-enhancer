# Fable 5 application-wide sweep — checkpoint 20

Status: complete for this bounded review and repair batch. Six Fable 5 reviews produced 22 confirmed repair groups; frontend, browser, targeted backend, build, API and privacy gates passed. This is not certification that every product feature or native integration is finished.

## Baseline and scope

This is a second independent review, requested with Fable 5. It preserves all uncommitted checkpoint 19 repairs. It does not reset to the older Git commit or count previously fixed defects as new work.

The installed Claude CLI reports version 2.1.231. A content-free probe returned the expected marker and reported `claude-fable-5` as the primary model, alongside its Haiku helper. The six audits and three bounded patch proposals also reported Fable 5. Reviews used high effort, safe mode, disabled tools/customizations, no session persistence, and only explicitly selected public application source and fictional fixtures. No provider sessions, credentials, owner configuration, screenshots, or real transcript excerpts were sent to the reviewer. Full CLI envelopes were not copied into the repository.

Baseline verification from checkpoint 19: 1,460 frontend tests, 67 browser tests, and 3,608 backend tests passed. Nine backend symlink checks could not run on this Windows host. These results are a baseline, not evidence for future changes.

## Review map

| Review | Surface groups | Focus | Status |
| --- | --- | --- | --- |
| Navigation/tasks | UI-00/01/02/13/16 | Navigation, catalogs, workspace, reviewed tasks and lifecycle | Reviewed; FB-01–04 |
| Agent/models/native | UI-15/18/20 | Session start/chat/editor, model lifecycle, native host | Reviewed; FB-05–08 |
| Metrics/quality | UI-03/04/05/06/10 | Exact values, ensemble, history/radar/stages, analysis and sharing | Reviewed; FB-09–11 |
| Evidence/jobs/sources | UI-07/08/09/12/14 | Evidence/receipts, consent/source controls, jobs and automation | Reviewed; FB-12–14 |
| Prompt/calibration/research | UI-11/15/17 | Prompt checks, calibration, coaching/judge/model-link, benchmark/readiness | Reviewed; FB-15–18 |
| Team/social/live | UI-18/19/20 | Team folders/visibility, conversations/transfers, auxiliary window | Reviewed; FB-19–22 |

Each review was limited to concrete findings. The orchestrator checked contracts and regression evidence, corrected patch proposals, and integrated the repairs. A model's report alone was not treated as proof. Browser inspection used the synthetic application and isolated workflow fixtures, not owner history. Areas reviewed without a new confirmed defect were not rewritten for appearance alone.

## Acceptance ledger

These are repair groups, not a count of independently proven defects. Each row names the focused regression surface; all of these tests are included in the final frontend run. Missing values remain unknown, generated commentary remains separate from objective evidence, and native approval and retention policies are unchanged.

| ID | Confirmed problem and repair | Regression evidence |
| --- | --- | --- |
| FB-01 | A failed initial health check stranded the shell. Added an explicit read-only **Recheck local service** action. | `App.test.tsx`: initial failure followed by successful recheck. |
| FB-02 | Retrying a rejected lazy import reused React's cached rejection. Added a fresh lazy-load attempt after failure and an explicit app-reload fallback. Healthy route changes retain the same attempt and do not remount the workspace. | `App.test.tsx`: rejected import recovers; healthy workspace state survives route-key changes. |
| FB-03 | A project removed from a refreshed catalog could remain selected for combining. Prune selections against the verified catalog, not the visible search filter. | `ProjectCatalog.test.tsx`: a removed selected project no longer keeps the combine action available. |
| FB-04 | A valid deep-linked session beyond the first 100 project sessions looked absent. Resolve the selected session through validated, bounded pages; after the first 1,000, offer an explicit next-1,000 lookup. Keep the visible catalog and aggregate-analysis limits unchanged. | `ProjectWorkspace.test.tsx`: session 101 resolves; session 1,001 requires continuation; navigation and focus remain intact. |
| FB-05 | An acknowledged editor write followed by failed readback looked like a failed write. Preserve the applied receipt and draft; block another write until a read-only reload reconciles the file. Ambiguous write failures are not called success or blindly retried. | `AgentWorkspacePane.test.tsx` and browser fixture: apply once, fail readback, reload without a second apply. |
| FB-06 | Folder errors had no recovery and late editor reads could outlive their session/transport. Added folder retry/refresh, separate loading states, abort signals and operation ownership. Wrapped editor header controls for narrow windows. | Editor tests: folder retry and stale transport responses; populated browser workflows at 360 and 1440 px. |
| FB-07 | Acknowledged session deletion depended on a subsequent list refresh. Remove the deleted session locally on acknowledgment so a failed refresh cannot leave it selectable. | `AgentPage.test.tsx`: deletion succeeds, refresh fails, deleted session stays absent. |
| FB-08 | Late chat, stop, approval or model feedback could affect a different selected session; approval errors could remain after success. Bind feedback to session/transport/version and clear superseded errors on explicit actions. | Agent tests: old-session failures/results cannot select it or clear the new draft; successful approval clears the previous rejection. |
| FB-09 | Preview expiry could invalidate the acknowledgment of an approval dispatched while the preview was valid. Expire the preview but preserve ownership of the already-started request. No new approval is allowed after expiry. | `AnalyzeLocallyDialog.test.tsx`: deferred approval finishes after the fake-clock expiry with its receipt intact. |
| FB-10 | Healthy ensemble polling erased a failed command's error. Separate read-health recovery from command feedback; only the next explicit command supersedes that error. | `ModelEnsemblePanel.test.tsx`: failed start remains visible across healthy polling. |
| FB-11 | Metric history reads could stop silently or have no recovery. Apply the existing bounded retry budget to transient failures/head mismatches; reject mismatched identities/definitions; offer explicit history retry. Unknown history is not described as zero stored snapshots. | Ensemble/history tests: retry cap, manual recovery, wrong identity and unknown-history presentation. |
| FB-12 | A recoverable server evidence-binding mismatch could strand the panel. Offer exact-source contract retry for load failures. Failed presence probes may leave inert preview/import available, but cannot enable native review or acceptance. | `RequirementActionEvidencePanel.test.tsx`: wrong server binding then recovery; absent presence and malformed capabilities remain fail-closed. |
| FB-13 | One failed job poll could stop live refresh indefinitely. Add three bounded read retries with 5/10/20-second backoff, then explicit retry. Retain last verified rows as stale; reset them on owner/filter/page changes. Never replay cancellation commands. | `AnalysisJobCentre.test.tsx`: poll recovery, exhaustion, manual recovery and exact cancellation ownership. |
| FB-14 | Label save/clear/enrichment acknowledgments disappeared when metadata refresh failed. Retain the acknowledgment, mark metadata stale, disable stale controls and offer a read-only reload. Ignore late feedback from a replaced transport. | `LocalSources.test.tsx`: all three acknowledged operations survive failed refresh; reload does not repeat the command. |
| FB-15 | Starting a model-link run could abort the initial stored-metadata read and leave no recovery after failure or cancel-wait. Retry the unknown metadata read and expose a manual retry without restarting the model job. | `ModelLinkExperimentPanel.test.tsx`: failed run, cancel-wait and metadata-read recovery; stale-owner isolation retained. |
| FB-16 | Remote annotation errors were hidden behind the modal and permitted an immediate duplicate send despite an unknown outcome. Keep the error inside the modal, mark the submission uncertain, disable resending in that view and keep Cancel usable. | `CalibrationPage.test.tsx`: uncertain response remains visible and cannot be blindly resubmitted. Real remote reconciliation is not implemented. |
| FB-17 | Model-judge guidance depended on raw text or conflated all conflict responses with an inactive model. Transport now preserves documented safe reason codes for judge/explanation/sweep calls; UI only gives inactive-model guidance for those exact codes. | `httpTransport.test.ts`, calibration and judge tests: inactive-model reasons versus unrelated or unknown 409 responses. |
| FB-18 | Failed or unavailable runtime inventory reads stayed at “Checking.” Show runtime/device availability as unknown and offer an explicit retry when supported, without launching a benchmark or downloading a model. | `ResearchLab.test.tsx`: missing API, failed read and successful read-only recovery. |
| FB-19 | Live refresh remounted timeline components and reset zoom/category/range. Refresh through a token while preserving view state; reset only when the timeline owner or transport changes, and validate returned identity. | Live/session/project timeline tests: manual and timed refresh preserve controls; changed owners cannot inherit the old view/data. |
| FB-20 | Live metadata failures and malformed first-pass fractions could appear as empty/valid results. Separate unavailable, stale and absent states; validate finite integer fractions; clear cached data on 403/404/410 rather than retaining revoked/deleted timelines. | Live/timeline tests: metadata errors, invalid fractions, denial/deletion and explicit read retry. |
| FB-21 | Team sharing claimed a one-time token was shown even when the response contained none. Use truthful token-absent success copy and explain that new peers cannot join without a token. | `TeamFoldersPanel.test.tsx`: successful share with a null token. |
| FB-22 | Team aggregate read failures could be mislabeled as an intentionally unserved scope with no retry. Reserve that state for `scope_not_served`; show other failures with retry of the same immutable scope. | `TeamAnalyticsPage.test.tsx`: failed scope read then recovery without changing query identity. |

## Reviewed proposals that were corrected or rejected

- The analysis dialog already had a workspace completion receipt from checkpoint 19. That was not counted again; the new repair is the narrower preview-expiry/in-flight-approval race. Exact-context approval checks remain in place.
- An invalid immutable evidence-binding prop cannot be repaired by refetching the same invalid prop. Retry was added for recoverable server load mismatches, not used to weaken binding checks.
- Not every HTTP 409 means “no active model”: the backend also uses it for other conditions such as an unavailable window. Only allowlisted reason codes produce that advice; arbitrary error bodies remain hidden.
- Retaining a stale timeline is acceptable for transient read failure, not for denied, removed or gone resources. Fable's retention proposal was tightened to clear those responses.
- A new lazy component on every route change would reset healthy workspace state. The first implementation was corrected and a state-preservation regression added before final validation.
- A selected-session lookup was separated from initial catalog loading after integration tests exposed unnecessary navigation/focus resets. Pagination remains bounded and never authorizes aggregate analysis over an incomplete catalog.
- Benchmark actions already respected their capability guards. That alleged missing guard was not counted as a new repair; the runtime-read recovery was.
- “Uncertain remote submission” is a UI guard, not server reconciliation or a claimed successful upload. No authoritative submission-status endpoint was invented.

## Final verification

| Gate | Command or method | Result |
| --- | --- | --- |
| Complete frontend | `npm test -- --maxWorkers=3` in `frontend` | **1,518 passed across 122 files**; 58 more tests than checkpoint 19. |
| Synthetic browser | `npm run test:e2e -- --workers=3` in `frontend` | **63 passed**; includes four new editor/live cases across 360 and 1440 px. |
| Local HTTP contract browser | Existing isolated local-browser test configuration | **8 passed**; API responses intercepted with fictional fixtures, not owner data. |
| Targeted backend | `.venv/Scripts/python.exe -m pytest tests/test_model_judge.py tests/test_model_judge_availability.py tests/test_privacy_scan.py tests/test_privacy_scan_exclusions.py -q` | **61 passed**; one existing dependency deprecation warning. |
| TypeScript and production build | `npm exec tsc -- -b --pretty false`; `npm run build` | Passed. Dev-only workflow fixture also passed a separate strict type check. |
| Generated API contract | `npm run check:api` in `frontend` | Passed. |
| Privacy/secret scan | `.venv/Scripts/python.exe scripts/privacy_scan.py` | Passed, including final checkpoint notes. |
| Whitespace | `git -c core.safecrlf=false diff --check` | Passed. |
| Interactive browser inspection | Synthetic editor and live-window fixtures | Applied-write/readback recovery and zoom/filter-preserving refresh checked directly; no horizontal overflow at the inspected width. No screenshots saved in the repository. |
| Running app | Protected desktop entry point; loopback health and rebuilt asset requests | Both HTTP 200. |
| Model cleanup | Local runtime process check | No test model activated by this sweep; zero `llama-server` processes observed. Other GPU applications left alone. |

No backend production code changed in checkpoint 20. The complete backend suite was **not rerun** in this batch: checkpoint 19's 3,608 passes and nine Windows symlink skips remain baseline evidence only. The targeted 61-test run above is the current backend verification. The dependency warning concerns the test client's deprecated `httpx` integration.

The browser-control skill guided direct inspection of the actual synthetic component states, in addition to automated tests. That inspection also informed the editor's narrow-width header wrapping. Browser fixtures establish UI behavior and API contracts, not actual GPU inference, native confirmations, peer transfers or remote annotation delivery.

## Remaining boundaries

The intentional boundaries and unfinished work in [checkpoint 19](checkpoint-19-handoff.md) remain open unless explicitly implemented and verified here. In particular:

- Owner visual approval and real selected-model usefulness are not established by fictional transports. No local model was loaded in this pass.
- Native folder picking, native confirmation, real filesystem writes and real peer transfers still require their protected, explicitly approved checks. Browser tests do not bypass those controls.
- Agent conversations remain memory-only. Durable chats, per-turn timing/token telemetry and richer changed-file summaries remain separate features.
- Remote annotation needs authoritative outcome reconciliation before a true safe retry can be offered. The current uncertain-outcome guard prevents a blind repeat in the view; it does not survive all reloads or establish remote success.
- The previous native app was no longer listening when checked. The rebuilt protected app was reopened successfully, but the earlier shutdown/packaged-launcher cause was not established or fixed by that restart.
- Symlink-boundary tests still need a host that permits creating symlinks.
- Hosted identity/billing, cross-machine publication, real transcript sharing and changed retention policies are not authorized or completed by this sweep.

All prior and new working-tree changes remain uncommitted. No commit or push was requested for this checkpoint. The compact review checklist and next-step boundary are in [checkpoint 20's handoff](checkpoint-20-handoff.md).
