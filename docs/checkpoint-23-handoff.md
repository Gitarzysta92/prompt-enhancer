# Checkpoint 23 — truthful model completion and partial-response recovery

Status date: 2026-08-26

Status: Agent and Models chat repairs implemented and verified. The whole-application goal remains open, including the separate old synthetic-fixture privacy finding. Previous checkpoint changes are preserved; no commit or push was performed.

## Reproduced failures

- Agent treated token-limit, filtered and unrecognized finish reasons as successful completion. Even valid-looking tool calls from that unfinished response could reach the tool loop.
- Whole-response fallbacks ignored missing completion receipts. A late whole response could also be published as complete after Stop.
- Reasoning-only Agent responses appeared complete despite containing no final answer or tool request.
- Models chat accepted dropped or malformed streams, lost a final event without a trailing newline, and left response readers locked. Stopped/failed partial answers could enter later model history.
- Models chat ignored token-limit and other non-success finish reasons, so the visible reply lacked an incomplete state and retry guidance.

The initial reproduction failed 27 backend and 24 frontend cases. A second check reproduced five reasoning-only/late-Stop failures before their repair. These are parameterized regression cases, not a claim of 56 unrelated defects.

## What changed

Agent now requires a valid completion receipt and respects its meaning. Incomplete output keeps its visible text and model-provided reasoning, receives an explicit interrupted status and safe explanation, and is withheld from tool execution and completed model history. Stop owns late whole-response fallbacks too. Successful tool-call replies still use the existing validation and native approval boundary.

Models chat has a bounded response reader that validates framing, field types, UTF-8 and termination; supports chunked/multiline SSE and whole JSON responses; and cancels/releases its reader on completion, rejection and abort. A finish receipt ends consumption without waiting indefinitely for a redundant marker or accepting later unsolicited output. Upstream errors and unknown finish strings are not displayed verbatim.

The conversation distinguishes complete, incomplete, interrupted and stopped replies. Partial output stays visible but is excluded from subsequent assistant history. An explicit retry resends the original message once and preserves the next unsent draft; nothing automatically retries a generation or tool action.

No analytics metric, task outcome, native approval permission or retention policy changed. A complete response means generation completed, not that its claims or code are correct. The existing API schema and Agent v3 contract remain unchanged.

## Verification on this snapshot

| Gate | Result |
| --- | --- |
| Full frontend | 1,589 tests passed across 123 files in 90.07 seconds |
| Focused frontend | 182 tests passed across response transport, Models chat and Models page; included in the full total |
| Focused backend | 126 tests passed across Agent, completion handling, local models, OpenAPI, runtime liveness and desktop lifecycle in 73.95 seconds |
| Synthetic browser suite | 77 workflows passed in 28.9 seconds, including six new completion/recovery cases |
| Intercepted HTTP browser suite | 16 tests passed in 16.6 seconds, including four new token-limit/dropped-stream cases through the real frontend HTTP transport |
| In-app browser cross-check | Six flows inspected: Models plus main/dedicated Agent views at 360 and 1440 px; incomplete notices, preserved partial text, recovery, retained drafts and no page-wide horizontal overflow |
| Build / contracts | Production build, generated API consistency, explicit strict browser-fixture/spec TypeScript and Python compilation passed |
| Whitespace | Passed |
| Privacy | Unchanged scanner still rejects the single old synthetic SQLite artifact; not a passing gate |
| Cleanup | Owned test listeners stopped, in-app test tab closed and viewport restored; zero model-runtime processes observed |

New unit coverage comprises 36 backend and 37 frontend cases. It includes no tool/approval admission from incomplete Agent responses, exact follow-up history, interrupted whole-response Stop, reasoning-only output, byte/text limits, malformed fields, UTF-8 splitting, terminal receipt cleanup, pending-read abort and retry draft preservation.

Commands:

- From the repository: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_local_agent.py tests/test_local_agent_completion.py tests/test_local_models.py tests/test_openapi_export.py tests/test_runtime_liveness.py tests/test_desktop_lifecycle.py -q --tb=short`.
- From `frontend`: `npm test -- --reporter=dot`, `npm run build`, `npm run check:api`, `npm run test:e2e -- --workers=3 --retries=0 --trace=off --output <fresh-test-directory>`, and `npm run test:e2e:local -- --workers=2 --retries=0 --trace=off --output <another-fresh-test-directory>`.
- From the repository: `.venv/Scripts/python.exe scripts/privacy_scan.py` and `git -c core.safecrlf=false diff --check`.

The HTTP browser cases intercept all application API traffic with fictional fixtures; they verify the frontend transport/UI together, not real inference. Backend tests likewise use synthetic upstream replies. No GPU model, provider sessions, credentials or owner configuration were used. The one existing test-client dependency deprecation warning remains.

The full backend suite was not rerun for this slice. Its earlier integrated results and Windows symlink skips remain historical evidence in the [checkpoint 21 handoff](checkpoint-21-handoff.md), not current passes. A synchronous whole-response upstream cannot be force-cancelled by this repair; its late result is marked stopped and excluded from history when it returns.

## Separate sign-off issue and remaining scope

The scanner finding is still `test-results/browser-workflow-e3rix2kz/application/shared-folders.sqlite3`, the old disposable synthetic database. No deletion was retried, alternate removal path used, or scanner exclusion added. The exact cleanup and required reruns remain in checkpoint 21. This finding does not prevent independent implementation work.

No restart/readiness claim is made for the normal owner application. Serve the rebuilt frontend with the updated backend and reload open pages before reviewing. No screenshot was stored in the repository.

Durable Agent retention, richer per-turn telemetry/changed-file summaries, owner calibration and visual acceptance, native-presence acceptance, symlink-capable testing and the previously recorded production/remote authorization gaps remain open. This checkpoint does not redefine the whole-application goal as complete.

## Review later

1. Models: when a reply hits its output limit or disconnects, confirm that partial text remains, the response is not labelled complete, and recovery guidance is visible.
2. Type a next draft and retry the previous message. The next draft should remain untouched and the retry should submit only once.
3. Agent: check the interrupted response and model-provided reasoning, then send a smaller follow-up. The new reply should complete while the earlier interrupted reply stays readable.
4. Stop/unload any model used for your manual review when finished.
