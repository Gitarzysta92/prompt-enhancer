# UI-04 · Metric workspace

Status: **frozen · implementation and automated verification complete**
Visual review: pending user review in the local app
Baseline: `b469803` (`feat(metrics): ship evidence-bound r7 requirement-action projection`)
Scope owner: `MetricWorkspace`, its exact-value board, lens selector, snapshot summary, and comparison context

## Frozen scope

This checkpoint changes only the canonical metric-workspace presentation and the context that must stay bound to its selected snapshot:

- the 20-contract receipt summary;
- the exact-value board and its initial/explicit selection;
- lens-selector semantics, focus, contrast, and narrow-container behavior;
- current-versus-comparison wording;
- pinned metric context and predictive detail when the run changes.

Radar geometry, knowledge-card content/layout, history and model-stage drawers, evidence workflows, backend contracts, migrations, and unrelated cards are not redesigned here.

## Accepted corrections

1. Partition all 20 canonical contracts into measured, legacy signal, pending, not applicable, unresolved, or no-receipt counts. These categories reconcile to 20 and state-only receipts are never promoted to measurements.
2. Promote the raw observed rate in the exact-value board for lower-is-better metrics. Keep the inverted percentage only as explicitly labelled radar orientation.
3. Render `Pending`, `N/A`, `Unknown`, `Needs evidence`, `Error`, and `No record` as explicit nonnumeric states; preserve a genuine measured zero as `0% measured`.
4. Prefer the first authoritative typed/V2 known receipt as the initial exact-value selection. Preserve an explicit valid selection across a refreshed snapshot.
5. Close a pinned metric knowledge card whenever its run identity changes, so content from run A cannot silently appear to describe run B.
6. Bind predictive detail to the exact `(run_id, metric_key)` request. Aborted, delayed, failed, or mismatched run-A responses cannot appear in run B.
7. Describe comparison geometry only when numeric comparison points exist in the selected lens. Otherwise state that the comparison is state-only, and use the caller-provided comparison label.
8. Replace the lens `nav` landmark with a labelled control group while preserving Arrow, Home, and End keyboard movement.
9. Add real workspace and exact-value headings/regions.
10. Collapse the snapshot and two-column primary grid at a 760 px workspace-container width, covering the clipped 861–1040 px viewport band without changing unrelated layouts.
11. Raise direct UI-04 copy to the 12 px floor, use defined color tokens, and give selected-lens text sufficient contrast in both themes.
12. Visually distinguish measured receipts from state-only receipts; pending and execution-error states retain distinct nonnumeric treatments.

## Explicitly deferred

- UI-05: radar and knowledge-card visual placement, long-copy layout, and pointer/focus polish. The bounded UI-04 audit identified full-mode radar header, predictive-detail, chunk-trace, and figcaption copy below the 12 px floor; that nested-surface accessibility repair is the first mandatory UI-05 item.
- UI-06: history and model-stage drawer presentation.
- UI-07 through UI-09: evidence import and native review cards.
- User visual approval. The local app contains private local data, so automated browser inspection was deliberately stopped before capturing or summarizing page content.

## Files changed

- `frontend/src/features/model-ensemble/MetricWorkspace.tsx`
- `frontend/src/features/model-ensemble/ModelEnsembleRadar.tsx`
- `frontend/src/features/model-ensemble/usePredictiveMetricDetail.ts`
- their focused workspace, overlay, panel, guidance, knowledge-card, and predictive-detail tests
- `frontend/src/styles.css`
- `docs/ui-card-review-backlog.md`
- this checkpoint note

## Automated verification record

- UI-04 focused regression suite: **108 passed**.
- Full frontend suite: **112 files / 1,122 tests passed**.
- TypeScript project build (`tsc -b`): **passed**.
- Production frontend build: **passed** (the existing ~515 kB main-chunk advisory remains).
- Repository privacy scan: **passed**.
- Repository diff check: **passed**; Windows LF→CRLF notices only.
- Localhost health: **HTTP 200** at `http://127.0.0.1:8765/`.
- The single bounded read-only audit found no blocker in the frozen UI-04 board/lens/snapshot scope. It found the nested full-radar 12 px issue recorded above for UI-05; no second audit loop was opened.
- No commit was created for UI-04.

## Later visual checklist

- Desktop, light and dark: the six receipt categories should reconcile clearly to 20 without making state-only values look measured.
- Exact values: confirm a lower-is-better example shows its raw observed rate as the main value and radar orientation only as secondary text.
- State tour: measured zero, pending, N/A, unknown, needs evidence, execution error, and no receipt must remain visually distinct and never look like numeric zero.
- Widths 1040, 900, 861, 760, 600, and 360 px: snapshot cells and radar/board columns must wrap or stack without clipping or horizontal overflow.
- Lens selector: selected text must remain readable in light and dark themes; Arrow keys, Home, End, Tab, and focus rings must remain clear.
- Snapshot A→B: pin a knowledge card, select a metric, then refresh. The card must close, the valid explicit selection may remain, and predictive detail must never show A under B.
- Comparison: verify numeric comparison copy only appears with dashed numeric marks; a state-only comparison must explicitly say no numeric comparison is available.
- Enlarged text: snapshot cells, board values, action copy, and comparison copy must wrap without overlap.
