# Metric workspace: module boundaries and extension seams

This note records the refactor that split the oversized metric-workspace files
into reusable, pure modules without changing API contracts or persistence.
Everything below uses synthetic fixtures only.

One deliberate truth fix accompanies the refactor: the history sparkline used to
let a typed receipt in a non-numeric state (unknown, abstained, error, N/A) fall
through to a known legacy committee value for the same key, while the radar for
the same point showed that state as unplotted. Both surfaces now resolve
receipts through one shared resolver (`modelEnsemblePrimaryMetrics`), so such a
point stays `null` in the history as well; the legacy committee value is read
only for legacy-only points that expose no typed receipts at all.

## Layering (dependency direction: top imports bottom, never the reverse)

```text
ModelEnsemblePanel.tsx / ModelEnsembleOverlay.tsx     surface state machines: polling, commands, watch scope
  └─ MetricWorkspace.tsx                              one workspace: header, lens nav, radar + board, drawers
       ├─ ModelEnsembleRadar.tsx                      radar SVG, axis strip, focused-metric inspector
       │    ├─ usePredictiveMetricDetail.ts           gated factor-density loading (abort-safe, key-checked)
       │    ├─ MetricKnowledgeCard.tsx                one-card-at-a-time knowledge overlay (role=region, never tooltip) + hidden descriptions
       │    ├─ metricGuidanceReceipt.ts               PURE: canonical V2 guidance receipt → exactly two sentences (state class as published, template ids, counts, censoring bounds, ≤2 measured focus factors)
       │    └─ metricHelpV2.ts                        versioned knowledge registry + legacy state-aware inspector sentences
       ├─ MetricDefinitionsAlert.tsx                  distinct `definitions_out_of_date` alert (update-client wording; replaces the workspace, never sits beside values)
       ├─ ModelConstellationDrawer.tsx                stage nodes + aria-live inspector
       │    └─ modelStages.ts                         PURE: stage grouping/roles, receipt adapters, summary label
       └─ MetricHistoryDrawer.tsx                     sparkline + snapshot buttons
            └─ trajectorySelection.ts                 PURE: history radar value, sparkline geometry, head/history reconciliation
  └─ useTrajectorySelection.ts                        hook: exact-snapshot loading over trajectorySelection
metricAxisModel.ts                                    PURE: lens axes, states, lower-is-better orientation, predictive gate, geometry, shared tile captions
canonicalPolling.ts                                   PURE: poll cadence, stale-head guard, PollCoordinator epochs
../../shared/ui/rovingFocus.ts                        framework-free arrow/Home/End keyboard helper
```

`ModelEnsembleRadar.tsx` re-exports `metricAxisModel` and `moveRovingFocus`, and
`MetricWorkspace.tsx` re-exports the trajectory helpers and `MetricWorkspaceHistory`,
so every pre-existing import path still resolves. New code should import the
pure modules directly.

## Single sources of truth (do not duplicate these)

| Concern | Owner | Notes |
| --- | --- | --- |
| Deep-model detection (`qwen`, `rubric`, `deep`) | `modelStages.isDeepModelStage` | Feeds both the "Deep judge" group and the radar's "at least two small experts" gate. |
| Metric status (`pending`, `missing`, value states) and labels | `metricAxisModel.modelEnsembleMetricStatus*` | Pending is a typed unknown with `episode_horizon_open`; never plotted, never zero. |
| Which receipt a surface reads for a key | `metricAxisModel.modelEnsemblePrimaryMetrics` / `modelEnsembleReceiptsByKey` | Typed projection only when the receipt exposes one, otherwise the legacy committee shadow; never mixed per key. The radar axes and the history sparkline (`modelEnsembleHistoryRadarValue`) both use it, so a typed unknown/abstained/error/N/A can never be replaced by a known committee value (`trajectorySelection.test.ts` asserts radar/history parity). |
| Lower-is-better orientation | `metricAxisModel.modelEnsembleRadarQualityValue` (`plotted = 1 - raw` for a known numeric receipt, otherwise `null`) | Used by `modelEnsembleRadarAxes` and the history value; raw rate remains available through `modelEnsembleAxisRawRateLabel`; the density is reversed with `modelEnsembleDensityBinsForDirection`. |
| Axis tile captions (strip + board) | `modelEnsembleAxisPlottedLabel`, `modelEnsembleAxisRawRateLabel`, `modelEnsembleKnowledgeEntries` | The board and the strip must never diverge; `metricWorkspaceSurfaces.test.tsx` enforces it. |
| Guidance/inspector input from an axis | `modelEnsembleAxisEvidence` | A non-known state never carries a numeric value; only typed explanation codes reach guidance. |
| The two guidance sentences every surface renders | `metricAxisModel.modelEnsembleAxisGuidanceSentences` → `metricGuidanceReceipt.metricGuidanceReceiptSentences` | A canonical V2 receipt is rendered from its sealed guidance receipt (`state_class` as published — a `known_retain` at the floor retains even if not every factor met; template ids; counts; exact censoring bounds; ≤2 focus factors only with `per_factor_measured`). The client never re-decides retain/improve from the value. Board, radar inspector, knowledge card and ARIA descriptions all call it (`metricGuidanceSurfaces.test.tsx` enforces parity). A compact history point without a guidance receipt says so instead of inventing a decision. |
| Client presentation ↔ registry binding | `metricPublicationV2Contract.metricDefinitionCompatibility` (pure, no fetch) | Bound to `registry_version=all-20-factor-contracts-v2`, `METRIC_CONTRACT_V2_SET_FINGERPRINT`, per-metric contract fingerprints and the guidance template catalog. A mismatch throws `MetricDefinitionsOutOfDateError`; the overlay/panel clear all twenty values and guidance and show `MetricDefinitionsOutOfDateAlert` (never "reconnecting"). |
| Objective measured count (of 5) | `metricAxisModel.modelEnsembleObjectiveMeasuredCount` | Header cell "Objective measured n/5" from `objective_measured_count` (or counted from compact V2 states). |
| Additive evidence readiness | `metricEvidenceReadiness.metricEvidenceReadinessForPublication` | Cross-binds all 20 ordered readiness rows to the exact publication, contract fingerprints and r1/r2 projection. The header distinguishes objective measurable from objective measured; cards and inspectors name exact proof contributors, adapter-required capability families, availability reason, calibration and product gate. A mismatch withholds the additive detail. |
| Predictive visibility gate | `modelEnsemblePredictiveVisibility` | Missing contributor proof (`null`) is distinct from a proven shortage (`< 2`). |
| Head/history selection + comparison overlay | `trajectorySelection.resolveTrajectorySelection` | Comparison only when both points are comparable and share a message window; the exact snapshot must carry the selected run id. |
| Stage receipt adapters + drawer summary | `modelStages.modelEnsembleStagesFor` / `modelEnsembleStageSummaryLabel` | Attempt rows outrank sealed stages; null case counts stay `null`. |
| Poll epochs and stale-head guard | `canonicalPolling` | Unchanged in this refactor. |

## Extension seams

- **Team or project views**: build axes with `modelEnsembleRadarAxes(run, lensId)`
  from any `ModelEnsembleRadarData` (aggregated receipts included) and render
  tiles with the shared caption helpers; the radar SVG and the board are only
  presentation over that model. Add a lens by extending `MODEL_ENSEMBLE_LENSES`
  from `qualityLenses` (a versioned lens keeps axis order fixed).
- **Model catalogs**: extend `modelStages` (`MODEL_ENSEMBLE_STAGE_GROUPS`,
  `modelEnsembleStageGroup`, `modelEnsembleStageRole`) in one place; the drawer,
  the small-expert gate, and any future catalog table read the same predicate.
- **New drawers**: follow `MetricHistoryDrawer`/`ModelConstellationDrawer`: a
  plain `<details>` so open state survives receipt refreshes, geometry or rows
  from a pure module, `moveRovingFocus` for button rows.
- **New surfaces over the trajectory**: reuse `useTrajectorySelection` (or the
  pure `resolveTrajectorySelection` in non-React code); the polling loops in the
  panel/overlay stay surface-specific because their identity and failure
  policies differ (per-session head vs active watch with disconnect tracking).

## Invariants covered by contract tests

- Full/compact workspaces render the same inspector sentences, history contract,
  and axis captions (`MetricKnowledgeCard.test.tsx`, `MetricHistoryDrawer.test.tsx`,
  `metricWorkspaceSurfaces.test.tsx`).
- Lower-is-better geometry, pending/unknown/N/A/missing semantics, explicit
  zeros, and the predictive gate (`ModelEnsembleRadar.test.ts`, `metricAxisModel.test.ts`).
- Exact head handling: only the requested snapshot id is admitted, stale or
  mismatched snapshots fall back to the aggregate point (`trajectorySelection.test.ts`,
  `useTrajectorySelection.test.tsx`, plus the existing panel/overlay suites).
- Predictive detail loading is gated, abort-safe, and key-checked
  (`usePredictiveMetricDetail.test.tsx`).
- Accessibility: roving focus, `aria-pressed`, `aria-live` inspectors, hidden
  knowledge descriptions, presentation-only SVG (`ModelConstellationDrawer.test.tsx`,
  `MetricKnowledgeCard.test.tsx`).

## Size/coupling evidence (lines, before -> after)

| File | Before | After |
| --- | --- | --- |
| `ModelEnsembleRadar.tsx` | 822 (model + component + a11y helper; 23 exports) | 429 (component only; model re-exported) |
| `MetricWorkspace.tsx` | 445 (workspace + stages + two drawers + trajectory helpers) | 193 (workspace only; helpers re-exported) |
| `ModelEnsemblePanel.tsx` | 668 | 635 (history reconciliation delegated) |
| `ModelEnsembleOverlay.tsx` | 987 | 956 (history reconciliation delegated) |
| new pure modules | - | `metricAxisModel.ts` 469, `modelStages.ts` 166, `trajectorySelection.ts` 136 |
| new components/hooks | - | `MetricHistoryDrawer.tsx` 66, `ModelConstellationDrawer.tsx` 93, `useTrajectorySelection.ts` 72, `usePredictiveMetricDetail.ts` 66, `shared/ui/rovingFocus.ts` 38 |
| largest file in the feature | 987 | 956 (overlay); largest presentation file 429 |

Coupling: `MetricWorkspace` no longer imports nine symbols from a React
component module; the panel and overlay import a hook and a type instead of a
component module; the duplicated deep-model regex and the duplicated
history/selection logic now have one owner each.
