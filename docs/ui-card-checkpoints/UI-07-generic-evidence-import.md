# UI-07 · Generic agent metric-evidence import

Status: **implementation complete · independent and integrated verification green**
Visual review: pending user review in the local app
Baseline: `84d4ef5`
Scope owner: generic `MetricEvidenceFilePanel` file preview, proposal import, and local decision surface

## Frozen scope

This checkpoint changes only the generic collaboration-lifecycle evidence-file surface:

- compact and full loading, unavailable, empty, ready, preview, stale, error, and confirmed presentation;
- canonical file selection and strict local preview feedback;
- unconfirmed proposal import and separate native confirm/reject decisions;
- exact `(session_id, source_run_id)` ownership across asynchronous work;
- bounded client-side file/media/schema errors;
- hierarchy, focus, keyboard cancellation, metadata wrapping, and narrow-container behavior.

Requirement-to-plan review, requirement-to-action review, backend contracts, provider adapters, generated/OpenAPI files, global styles, and metric calculations are not changed here.

## Accepted corrections

1. Filter loaded proposals to the current session and exact sealed run. Historical proposals can no longer appear as current review work.
2. Gate every rendered proposal, preview, error, notice, capability, and busy state synchronously by its owning `(session_id, source_run_id)`. Every exposed mutation handler independently rechecks the current prop binding, and in-flight work is aborted and verified again before state updates. Run A can neither appear nor act during the first run-B render, and a delayed A response cannot repopulate B.
3. Fail native decisions closed. Missing, failed, or unavailable user-presence capability leaves confirm and reject disabled; preview/import remains local and creates only inert proposals.
4. Distinguish initial loading from a genuine empty exact-run proposal set. Load failures have bounded copy and a local retry control.
5. Validate a non-empty `.json` file, accepted JSON/canonical media type, and the 64 KiB limit before reading or sending bytes.
6. Require preview session, sealed run, and unexpired lifetime to match. Raw file bytes, file names, exception details, and selected content are never rendered.
7. Require imported digest, proposal session/run, and proposed status to preserve the strict preview binding. A mismatch is stale and cannot become actionable.
8. Require a decision response to preserve proposal identity, session/run, status, and decision. Only a valid confirmation triggers metric-analysis refresh; rejection does not.
9. Keep confirmation and rejection as explicit two-step actions. Move focus to the decision action, restore it to the opening control after Cancel/`Escape`, and move it to durable success feedback after completion.
10. Add labelled level-three/level-four hierarchy, named regions, polite progress/status feedback, alerts, 44 px controls, visible focus, and long safe-metadata wrapping.
11. Add a panel-local 42 rem container collapse for the 360–1040 px band. Styling uses existing theme tokens and preserves forced-colors and reduced-motion behavior without changing global styles.
12. Report already confirmed/rejected decisions for the exact run without rendering them as actionable proposals.

## Privacy and authority boundary

- All tests use reserved synthetic identifiers and fictional producer metadata.
- UI messages are fixed and bounded; caught exception text is never surfaced.
- Raw selected bytes and file names are not inserted into the document.
- Producer metadata remains visibly labelled as an untrusted provenance claim, never evidence authority.
- Import still creates an unconfirmed proposal only. A native user-presence capability is required for a decision, and a new analysis is required to publish any confirmed effect.

## Files changed

- `frontend/src/features/model-ensemble/MetricEvidenceFilePanel.tsx`
- `frontend/src/features/model-ensemble/MetricEvidenceFilePanel.test.tsx`
- `frontend/src/features/model-ensemble/MetricEvidenceFilePanel.css`
- this checkpoint note

## Automated verification record

- Independent validation found and closed one P1: passive cleanup alone allowed A-owned preview/proposal state to survive until effects after a B render. The final implementation uses synchronous owner gating plus handler admission checks, with captured stale-action regressions.
- Independent exact-defect recheck: **passed**. Retained A import and decision handlers are inert on the first B render, and stale A state is absent before effect cleanup.
- Focused generic evidence-import regressions: **16 passed**.
- Existing `ModelEnsemblePanel` r5 generic-evidence routing integration: **1 passed**.
- TypeScript project build (`tsc -b --pretty false`): **passed**.
- Production frontend build: **passed** (the existing ~515 kB main-chunk advisory remains).
- Final integrated frontend suite: **112 files / 1,156 tests passed**.
- Repository privacy scan: **passed**.
- Owned-path diff validation: **passed**; Windows LF→CRLF notices only.
- Focused cases cover loading/empty/unavailable/confirmed states, exact-run filtering, synchronous first-render A→B preview/proposal gating, captured stale-action rejection, delayed preview reset, import/decision binding failures, load retry, fail-closed presence, file size/extension/media/schema bounds, raw-content non-rendering, confirm/reject separation, `Escape`, and focus movement.
- No localhost or private session content was inspected. Visual verification remains a later manual synthetic-data check.
- No commit was created by this implementation agent.

## Later visual checklist

- Full mode, light and dark: confirm the workflow hierarchy reads as file → preview → proposal → native decision, without making producer claims look authoritative.
- Compact mode: loading, unavailable, zero, one, and multiple proposal counts remain readable and expose no action buttons.
- Widths 1040, 900, 760, 600, and 360 px: file input, long safe producer/model codes, proposal labels, decision copy, and buttons wrap without clipping or horizontal page overflow.
- Keyboard: Tab reaches the picker and all enabled actions; preview focus, decision focus, `Escape`, Cancel, and durable completion focus are visible and predictable.
- State tour: unavailable transport, loading, empty exact-run set, ready proposal, strict-preview validation error, stale binding, import error, native confirmation unavailable, confirmed, and rejected.
- Snapshot A→B: start a preview or decision under A, change to B, and verify no A metadata, alert, proposal, or completion appears under B.
- Forced colors and enlarged text: boundaries, focus rings, alerts, and action order remain visible; no status relies on color alone.
