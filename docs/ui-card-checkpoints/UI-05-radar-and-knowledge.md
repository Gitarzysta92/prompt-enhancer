# UI-05 · Metric radar and knowledge cards

Status: **implementation complete · independent and integrated verification green**
Integration status: converged with UI-06/UI-07; final Wave 1 suite green
Visual review: pending user review in the local app
Baseline: `84d4ef5`
Scope owner: `ModelEnsembleRadar`, `MetricKnowledgeCard`, `MetricExplainer`, and their direct presentation rules

## Frozen scope

This checkpoint hardens the radar and its metric-help overlays without changing any metric contract, value, direction, authority, state, or comparison rule:

- full and compact radar typography and information hierarchy;
- radar/inspector accessible names and reading-guide structure;
- knowledge-card and explainer hover, focus, touch-pin, and Escape behavior;
- overlay anchoring, viewport clamping, and scroll/resize response;
- long metric labels, identifiers, evidence descriptions, and enlarged text;
- light/dark token use, forced-colors, reduced-motion, narrow viewport, and short viewport behavior.

History/model-stage drawers remain UI-06. Evidence import and native review cards remain UI-07 through UI-09. The exact-value board, receipt summary, run-change dismissal, predictive request ownership, and comparison truth remain the frozen UI-04 implementation.

## Accepted corrections

1. Raise the recorded full-radar header, predictive-detail, factor, chunk-trace, and figure-caption copy to the repository's 12 px floor. Normal inspector/help prose remains 14 px; compact surfaces retain a 12 px floor.
2. Give every radar figure a real lens heading and accessible figure name. Give the selected-metric inspector its own named region/heading, the model detail a metric-specific label, and the window trace a labelled group.
3. Split the dense reading guide into three readable paragraphs while preserving its exact geometry, state-lane, model-estimate, coverage, and non-composite-score semantics.
4. Capture trigger coordinates for pointer hover, keyboard focus, and pointer-down. Touch pinning no longer falls back to an unrelated bottom-right position when no hover occurred first.
5. Share the same anchor/clamping algorithm between knowledge cards and team explainers. Place a card outside the complete trigger row when space exists; otherwise use a viewport-contained scroll surface.
6. Recalculate open overlays after resize, zoom-driven viewport changes, and scrolling. Adjust captured coordinates for window scroll and keep a card inside the viewport when its original trigger leaves view.
7. Connect each trigger to its unique visible card with `aria-controls` and `aria-expanded`. Visible cards remain named non-modal regions, and hidden two-sentence descriptions remain available before a card opens.
8. Make each open scroll region keyboard-focusable, with a visible focus ring, so long pinned content can be read without a pointer. Preserve the single-card controller, delayed pointer bridge, focus preview, click/tap pin, Escape dismissal, and stale-key dismissal. A pinned card still blocks unrelated hover replacement until deliberately closed.
9. Allow radar headings, axis labels, values, provenance, factor names, evidence authority, and long identifiers to wrap. Replace rigid four-column fact layouts with bounded responsive columns.
10. Keep mobile receipt facts and window traces available instead of hiding them at 360 px or on a short viewport. Card bodies and factor lists scroll internally without expanding or clipping their parent surface.
11. Add explicit pinned-card, forced-colors, and reduced-motion treatments using existing semantic tokens. No theme-specific literal metric meaning was introduced.
12. Bind the shared card controller to an explicit, content-free context identity. A same-key A→B run, aggregate snapshot, grant, or member-page epoch now gates the old card out synchronously and dismisses pinned or transient state before the new guidance/provenance can render. Display labels and card copy are never hashed into this identity.

## Metric-truth boundary

- Raw measured values and radar-oriented coordinates are unchanged.
- Missing, pending, N/A, abstained, error, and withheld states remain nonnumeric.
- Predictive ranges remain independent experimental geometry and product-ineligible unless their existing receipt says otherwise.
- Knowledge text still comes from the sealed projection-specific metric-help registry and the existing guidance builder.
- The radar remains a secondary shape scanner, not a score or proof of outcome.

## Files changed

- `frontend/src/features/model-ensemble/ModelEnsembleRadar.tsx`
- `frontend/src/features/model-ensemble/MetricKnowledgeCard.tsx`
- `frontend/src/features/model-ensemble/MetricKnowledgeCard.test.tsx`
- `frontend/src/features/model-ensemble/MetricExplainer.tsx`
- `frontend/src/features/model-ensemble/MetricExplainer.test.tsx`
- `frontend/src/features/model-ensemble/MetricExplainer.css`
- `frontend/src/features/model-ensemble/MetricWorkspace.tsx` (existing sealed `runId` threaded to the shared controller)
- `frontend/src/features/team-analytics/TeamAggregateBoard.tsx` (server-issued aggregate query id plus generated epoch)
- `frontend/src/features/team-analytics/MemberVisibilityPanel.tsx` (canonical grant/request identity plus validated page epoch)
- `frontend/src/styles.css`
- this checkpoint note

## Automated verification record

- Direct UI-05 regression suite: **43 tests passed** across radar truth, knowledge cards, and team explainers, including same-key pinned and preview A→B context changes on both card implementations.
- Affected team-analytics regression suites: **55 tests passed** across aggregate, drawer, and member-visibility hosts.
- Independent exact-defect recheck: **passed**. Same-key pinned and preview cards are hidden synchronously on A→B→C context changes, and every affected host supplies a stable content-free owner identity.
- Direct source TypeScript check: **passed**.
- Full frontend TypeScript project build: **passed** after all Wave 1 edits converged.
- Production frontend build: **passed**; the existing approximately 515 kB main-chunk advisory remains.
- Repository privacy scan: **passed**.
- Final integrated frontend suite: **112 files / 1,156 tests passed**. A first four-worker run had one unrelated five-second timeout in a team-page test; that exact test passed alone, and the complete two-worker rerun passed without failures.
- Owned-path diff check: **passed**; Windows LF-to-CRLF notices only.
- No localhost/browser inspection was performed. The live app can contain private local data, and this checkpoint used synthetic fixtures only.
- No commit was created.

## Later visual checklist

- Desktop light and dark: verify the radar header wraps cleanly, the authority chip remains legible, and the selected axis/focused metric are unmistakable without implying a composite score.
- Read every full-mode header, predictive line, factor row, chunk trace, and caption at default and enlarged text; none should render below 12 px or overlap.
- Hover a first/middle/last axis near each viewport edge. The card should open outside the row, remain entirely on screen, and stay open while crossing the small trigger-to-card gap.
- Focus the same axes with Tab, move among axes with Arrow/Home/End, pin with Enter/Space, and close with Escape. `aria-expanded` and the visible region should track the same target.
- On a touch-sized viewport, tap an axis without hovering first. The pinned card should anchor to that row; tapping the control again or pressing Escape with a keyboard should close it.
- While a card is open, resize, zoom, and scroll. The card should stay viewport-contained and internally scroll long content instead of clipping controls underneath.
- Test 1040, 900, 760, 600, 400, and 360 px widths plus a short landscape viewport. Axis labels, inspector facts, factor names, and long fictional IDs must wrap; receipt facts and trace content must remain available.
- Exercise known zero, lower-is-better raw rate, pending, N/A, unknown, abstained, execution error, missing, visible prediction, and withheld prediction examples. UI-05 layout changes must not alter their existing values or wording basis.
- In forced-colors and reduced-motion modes, confirm selected/pinned boundaries remain visible and no transition is required to understand state.
