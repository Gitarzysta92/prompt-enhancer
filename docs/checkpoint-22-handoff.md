# Checkpoint 22 — Agent model-control ordering and recovery

Status date: 2026-08-26

Status: this bounded repair is implemented and verified. The separate repository privacy gate still rejects one old synthetic database; whole-application sign-off remains open. Earlier checkpoint changes are preserved. No commit or push was performed.

## What was wrong

A delayed model-status read could overwrite a newer, confirmed Start or Stop result. A successfully started model could appear stopped or unavailable; a stopped model could appear ready. Independent refreshes also accepted whichever response arrived last rather than the newest request.

Model commands had two additional ownership gaps: Send remained available while Stop was pending, and an old connection's unfinished activation or stop preflight could continue into session creation or model stopping after the connection was replaced.

Twelve synthetic regression cases failed before the repair. They cover stale success/error responses before and during Start/Stop, pending-stop controls, reversed refresh order and both connection-replacement paths.

## What changed

- Model reads and commands now belong to the current connection. Only its latest applicable read can update readiness; confirmed commands invalidate older observations both when they begin and when they settle.
- Starting and stopping have explicit pending labels. Send and Check & improve are unavailable for the affected model until the command settles, and the unsent draft is preserved.
- A replaced or unmounted connection cannot continue an old preflight into another mutation, update the new connection's state or release its busy controls. This does not cancel a runtime command that was already issued.
- A failed command leaves model status unverified and offers a fresh status check. A delayed old success cannot falsely recover it. Fresh observations after a settled command remain accepted.

Native approval boundaries, session retention and backend/API behavior are unchanged. This checkpoint does not add durable conversations, new model capabilities or a redesigned coding-chat interface.

## Current verification

| Check | Result |
| --- | --- |
| Full frontend | 1,552 tests passed across 122 files in 94.59 seconds; includes all 72 Agent component tests |
| New Agent coverage | 16 new tests, including the 12 pre-fix failures and additional failure-recovery, unmount, connection-ownership and fresh-observation cases |
| In-app browser | Four synthetic workflows passed: main and dedicated Agent views at 360 and 1440 px |
| Browser acceptance | Hold an older status response, Start/Stop the model, release the old response; confirmed readiness, composer state and draft preservation remain correct, with no page-wide horizontal overflow |
| Build / API | Production build and generated API consistency check passed |
| Browser TypeScript | Explicit strict checks passed for the fixture and browser specs |
| Whitespace | Passed |
| Privacy | Unchanged scanner reports one prohibited artifact, described below; not a passing gate |
| Test-resource cleanup | Owned loopback test listener stopped, test tab closed and viewport restored; zero `llama-server` processes observed |

Commands: `npm test -- --reporter=dot` and `npm run build` from `frontend`; `npm --prefix frontend run check:api`; `.venv/Scripts/python.exe scripts/privacy_scan.py`; `git -c core.safecrlf=false diff --check`.

The in-memory development fixture now offers a synthetic delayed-status control, and four matching reusable browser cases were added. These cases were typechecked and exercised through the in-app browser; the entire standalone browser suite was not rerun. Focused component runs are already included in the full frontend count, not added to it.

No backend source changed and no backend suite was rerun for this checkpoint. The earlier full-backend and real-model results remain historical evidence in the [checkpoint 21 handoff](checkpoint-21-handoff.md), not new runs. No GPU model, owner sessions, credentials or owner configuration were used for this slice.

## Separate privacy cleanup

The scanner still rejects `test-results/browser-workflow-e3rix2kz/application/shared-folders.sqlite3`, an old disposable synthetic fixture from the earlier connection-leak reproduction. This is a prohibited repository artifact, not evidence that private session data was discovered. Its earlier deletion attempt was denied before execution; no new removal attempt or alternate deletion path was used in this checkpoint. No scanner exclusion or assertion was weakened.

After that exact old fixture is removed through an authorized path, rerun the scanner and the repository privacy assertion documented in checkpoint 21. Until then, do not commit the artifact or report the overall gate as green. Independent repairs can still proceed.

## Review later

1. In an existing disposable Agent session, start the selected model. Confirm the starting label changes to ready and the composer becomes available.
2. Type a harmless draft, then stop the model. Confirm the stopping label appears, Send and Check & improve are unavailable, and the draft remains after the model stops.
3. Check both the main Agent page and its dedicated window at your preferred size. Report any remaining confusing model/session distinction separately from this ordering repair.

No restart or readiness claim is made for the owner's normal application instance. Review needs rebuilt assets to be served and open pages reloaded. This checkpoint is not a claim that every model, native interaction or application feature is correct.
