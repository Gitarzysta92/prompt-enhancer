# Checkpoint 20 — Fable 5 review and repair pass

Status date: 2026-08-26

Status: six bounded Fable 5 audits completed; 22 repair groups integrated and regression-verified. Existing checkpoint 19 changes were preserved. No commit or push performed.

## What changed

- Agent/editor: applied changes and deleted sessions keep their acknowledgments when refresh fails; folder/file reads can recover; late responses stay attached to the correct session; approval feedback clears correctly; narrow editor controls fit.
- Navigation/catalogs: local-service and failed-page retries work; healthy navigation retains workspace state; removed selections are pruned; older selected sessions can be found through bounded paging.
- Metrics/evidence/jobs: command errors survive healthy polling, history has bounded recovery, in-flight approved analysis survives preview expiry, evidence retries stay exactly bound, and job polling recovers without repeating commands.
- Calibration/research/sources: saved labels survive failed refreshes; unknown remote submission is visible and blocked from blind resending; inactive-model advice uses safe exact codes; stored model-link metadata and runtime status have read-only recovery.
- Live/team views: refresh retains zoom and filters, stale/unknown/denied data is distinguished, invalid fractions stay unknown, absent share tokens are described honestly, and failed team reads can retry the same scope.

The [full Fable sweep ledger](fable-5-sweep-2026-08-26.md) records each repair, regression surface, corrected review proposal and remaining boundary. Findings were checked, not accepted solely because a reviewer reported them.

## Verification

| Gate | Result |
| --- | --- |
| Frontend | 1,518 tests passed across 122 files; 58 more than checkpoint 19 |
| Browser | 63 synthetic + 8 isolated local-contract tests passed |
| Targeted backend | 61 passed; one existing dependency warning |
| TypeScript, production build, generated API contract | Passed |
| Privacy/secret scan and whitespace | Passed |
| Interactive browser checks | Synthetic editor recovery and live refresh inspected; narrow/desktop workflows covered by browser tests |
| Local app | Protected desktop app reopened; loopback health and latest built asset returned HTTP 200 |
| GPU cleanup | No local test model loaded; zero `llama-server` processes observed |

No backend production code changed. The full backend suite was not rerun here; checkpoint 19's 3,608 passes and nine Windows symlink skips are prior evidence, not new passes. Fixture tests do not certify real inference, native confirmation or external delivery.

## Review when convenient

Open [Agent](http://127.0.0.1:8765/agent). Keep its protected desktop window open: it owns the service and memory-only sessions. Ordinary browser windows do not gain native permissions from these fixes. Reload any previously open browser tab to pick up the rebuilt frontend; do not do so mid-action.

1. Agent: select a workspace and model, open chat, send one harmless request, switch sessions and confirm feedback stays with the session that initiated it. Stop the model afterward; the conversation should remain visible.
2. Editor: use a disposable fictional file if testing a write. Review the diff and native approval. An applied receipt should not disappear just because the following read fails; use Reload file to reconcile, not a second Apply.
3. Live view: zoom and hide one tool category, then refresh. The viewport and filter should remain unchanged. A genuinely unavailable resource must not look like current data.
4. Recovery controls: recheck service, retry a failed page/history/read, and review label-save feedback. Read retries must not restart analysis, repeat a write or submit another remote batch.
5. Narrow window: check Agent, editor, prompt results and live view for clipping, inaccessible controls and confusing copy. Record one specific card/action at a time.

These checks do not require sharing private transcripts or uploading screenshots. Use fictional content for anything that becomes a repository fixture or bug report.

## Not certified finished

- Real model quality and card-by-card visual preferences still need owner review.
- Native picker/confirmation, real peer transfer and symlink boundaries need their relevant integration environment.
- The earlier native shutdown/packaged-launcher cause remains unresolved; reopening the app is not a diagnosis.
- Durable Agent conversations, richer per-turn telemetry and changed-file summaries remain separate features.
- Remote annotation has an uncertain-outcome guard, not an authoritative delivery-status/reconciliation service.
- Publication, identity/billing and content-retention changes retain their existing authorization gates.

Next checkpoint should target one recorded owner finding or one named unfinished feature, with its acceptance test written first. This batch is complete; another open-ended redesign pass is not implied.
