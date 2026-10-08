# UI-03–UI-07 · Synthetic integration tour

Status: **implementation complete · integrated verification green**
Baseline: `5e9bd7b` (`docs(ui): record wave one checkpoint status`)
Visual review: pending user review in the local app

## Purpose and boundary

This checkpoint adds host-level synthetic tests only. It does not change production components, contracts, generated files, provider adapters, or application data.

The tour proves that the frozen UI-03 through UI-07 surfaces cooperate as one workflow:

- canonical model-ensemble shell and current sealed metric workspace;
- radar selection and pinned exact-metric help;
- numeric plus missing history and attempt-stage provenance;
- generic evidence preview, inert import, and native confirmation;
- synchronous run and transport ownership across full and compact workspace hosts.

UI-08 and UI-09 are deliberately mocked in this test because their independent implementation lanes were still active when the UI-03–UI-07 tour froze.

## Accepted coverage

1. The real `ModelEnsemblePanel` host reaches the canonical workspace, radar/help, history/stages, generic evidence preview/import, and one valid native confirmation callback with exact synthetic transport arguments.
2. A paired full/compact `MetricWorkspace` host preserves receipt, history, model-stage, unknown-not-zero, and fail-closed native-presence truth.
3. Run plus transport A→B and same-run transport-only changes synchronously hide stale help, preview, proposal, history, and stage state.
4. Detached A/B import and decision controls remain inert after their owner changes.
5. Missing evidence capabilities expose no mutation controls.

## Files added

- `frontend/src/features/model-ensemble/ModelEnsembleCheckpointTour.test.tsx`
- `frontend/src/features/model-ensemble/modelEnsembleCheckpointTour.test-fixtures.ts`
- this checkpoint note

## Verification record

- New integration tour: **2 tests passed**.
- Affected UI-03–UI-07 host group: **10 files / 137 tests passed**.
- Final integrated frontend suite after UI-08/UI-09 convergence: **113 files / 1,189 tests passed**.
- TypeScript, repository privacy scan, and diff checks: **passed**.
- Production build: **passed** with only the existing approximately 515 kB main-chunk advisory.
- All fixtures use reserved synthetic identities and fictional content. No localhost, browser DOM, private session, credential, transcript, path, or screenshot was inspected.

## Known test-boundary limitation

`ModelEnsemblePanel` exposes only full mode. Compact/full parity and compact context attacks therefore use the public `MetricWorkspace` host, while the real-shell tour remains full-mode. This is a test-boundary limitation, not a claim that compact mode is broken.
