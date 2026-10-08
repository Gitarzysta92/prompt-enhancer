# UI-06 · Metric history and model stages

Status: **implementation complete · independent and integrated verification green**
Visual review: pending user review in the local app
Baseline: `84d4ef5` (`fix(ui): harden metric workspace truth and context`)
Scope owner: `MetricHistoryDrawer`, `ModelConstellationDrawer`, model-stage receipt presentation, and their scoped presentation rules

## Frozen scope

This checkpoint hardens the two metric-workspace disclosures and preserves the attempt-stage unload receipt's existing tri-state contract without changing backend contracts, trajectory selection, metric computation, evidence workflows, or other cards:

- sealed metric history identity, comparability, receipt-state truth, and selection;
- history empty, delayed-refresh, unavailable, and stale-selection states;
- model-stage source, status, resource, revision, case-count, and authority provenance;
- disclosure, keyboard, semantic grouping, narrow-layout, theme, high-contrast, and text-size behavior.

## Accepted corrections

1. Each history row now identifies the current or earlier generation, short immutable run identity, selected state, and comparability to the current snapshot.
2. Numeric receipts and state-only receipts are labelled separately. Unknown, N/A, needs-evidence, error, pending, known-without-numeric-value, and missing receipts never become zero.
3. Lower-is-better history rows retain the raw rate and separately label the once-inverted chart orientation. A genuine numeric zero remains numeric.
4. The chart states its numeric coverage and omits the numeric plot entirely when every loaded receipt is state-only or missing. Lines still connect only adjacent points that are both comparable to the head.
5. All loaded trajectory rows are rendered; the drawer no longer silently stops after eight while claiming a larger snapshot count.
6. Undefined history, an empty loaded trajectory, delayed refresh with prior rows, and delayed refresh without prior rows have distinct messages.
7. A requested run from context A that is absent from context B cannot remain visually selected. The loaded current snapshot becomes the effective selection and the reset is stated.
8. Snapshot buttons support Arrow, Home, and End focus-and-select behavior while retaining the established live/earlier accessible names used by both workspace hosts.
9. Model-stage provenance is stated both for the drawer and selected inspector: latest durable attempt versus sealed snapshot.
10. Stage selection is synchronously bound to its exact sealed-run identity or the latest-attempt stage-receipt identity available to this component, so an inspector selected in A cannot silently describe B even when model keys repeat.
11. Missing device, latency, memory, revision, unload, and case-count facts remain explicitly unrecorded or unavailable. Unload receipts preserve true, false, and unknown as separate facts; recorded zero latency, memory, and contribution counts remain zero.
12. Compact mode retains the same provenance facts as full mode; layout, not truth, is compacted.
13. Model groups use labelled sections and headings. Arrow, Home, and End update both focus and the live inspector.
14. Long content-free repository and revision identities wrap or expose their exact value without clipping the inspector.
15. Scoped styles raise direct drawer copy to a 12 px floor, use semantic theme tokens, stack at a 520 px container, preserve 44 px controls, and include reduced-motion and forced-colors treatments.

## Explicitly deferred

- Retry commands are not part of either drawer prop contract. UI-06 reports delayed refresh truthfully and does not invent a retry action; transport-owning hosts remain responsible for retry/recovery commands.
- Attempt-stage props do not expose an `attempt_id`; the drawer therefore keys attempt context from the first durable stage receipt's ordinal, key, and completion identity. A future prop-contract change may pass the durable attempt identity directly, but UI-06 does not invent one.
- Trajectory fetching, exact historical-snapshot loading, comparison eligibility, and stage grouping remain in their existing pure/host modules. Attempt-stage normalization changes only by preserving the API's existing `true | false | null` unload receipt instead of collapsing `null` to `false`.
- Evidence import/review cards, radar/knowledge cards, backend schemas, and generated API files are outside this checkpoint.
- Browser visual review is intentionally left to the user because the running local app may contain private local data. No localhost content is inspected or captured by this checkpoint.

## Files changed

- `frontend/src/features/model-ensemble/MetricHistoryDrawer.tsx`
- `frontend/src/features/model-ensemble/MetricHistoryDrawer.test.tsx`
- `frontend/src/features/model-ensemble/ModelConstellationDrawer.tsx`
- `frontend/src/features/model-ensemble/ModelConstellationDrawer.test.tsx`
- `frontend/src/features/model-ensemble/modelStages.ts`
- `frontend/src/features/model-ensemble/modelStages.test.ts`
- `frontend/src/features/model-ensemble/MetricHistoryAndStages.css`
- this checkpoint note

## Automated verification record

- Direct UI-06 component and stage-adapter suite: **3 files / 26 tests passed**.
- Host integration suites: **2 files / 67 tests passed**.
- Independent exact-defect recheck: **passed**. The adapter and drawer preserve and render `true`, `false`, and `null` unload receipts as three distinct facts; unknown is never shown as explicit false.
- TypeScript compile check (`tsc --noEmit`): **passed**.
- Final integrated frontend suite: **112 files / 1,156 tests passed**; the production build also passed with only the existing approximately 515 kB main-chunk advisory.
- Repository privacy scan: **passed**.
- Owned-path diff check: **passed**; Windows LF→CRLF notices only.
- No backend, generated contract, global stylesheet, localhost data, or real session fixture was touched.
- No commit was created by the UI-06 implementation agent.

## Later visual checklist

- Open and close both disclosures with pointer, Enter, and Space; the chevron and focus ring must remain clear in light and dark themes.
- History numeric tour: higher-is-better, lower-is-better, and genuine zero. Raw and chart-oriented values must not be confused.
- History state tour: pending, N/A, unknown, needs evidence, error, known without a number, and no record. An all-state trajectory must not show an empty numeric graph.
- Select an earlier snapshot, then refresh from trajectory A to unrelated B. Only B's current row and chart point may be selected.
- Confirm current, selected, comparable, and scope-break labels remain readable with 200% text zoom and long synthetic run identities.
- Select a deep stage, then move from sealed run A to B and from a sealed source to a latest-attempt source. The inspector must reset to a stage belonging to the new context.
- Verify completed, failed, resource-exhausted, unavailable, and cancelled stages without relying only on marker color.
- Verify missing resource facts say `not recorded` or `unavailable`, while a recorded `0 ms`, `0 MiB`, or `0` contributed cases stays zero.
- Verify unload receipts separately: `true` says unloaded, `false` says not unloaded, and `null` says the unload receipt is missing.
- Widths 1040, 900, 760, 600, 520, and 360 px: snapshot cards, stage nodes, inspector facts, repository names, and revision identities must wrap without horizontal page overflow.
- Repeat at light, dark, forced-colors/high-contrast, reduced-motion, and enlarged-text settings.
