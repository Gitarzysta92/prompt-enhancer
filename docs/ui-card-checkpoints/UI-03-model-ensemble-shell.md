# UI-03 · Canonical model-ensemble shell

Status: **frozen · implementation and automated verification complete**
Visual review: pending user review in the local app
Scope owner: `ModelEnsemblePanel` outer shell and its direct project-workspace integration

## Frozen scope

This checkpoint changes only the shell around the canonical metric workspace:

- heading and primary run action;
- continuous-watch control;
- loading, verified-empty, unavailable/retrying, blocked, outdated, running, and terminal status;
- shell-level accessibility and narrow-screen behavior;
- the redundant parent landmark around this panel.

Nested metric, radar, history, model-stage, and evidence-card layouts are not redesigned here.

## Accepted corrections

1. Do not report “no stored analysis” until the receipt authority has actually returned a definitive empty result.
2. Keep loading, verified-empty, and temporarily-unknown/retrying states mutually exclusive.
3. Serialize run, cancellation, and watch mutations; ignore or abort results from an earlier component context.
4. Keep “Stop continuous updates” available after analysis consent/compatibility becomes blocked, while still preventing a new watch or analysis.
5. Make definitions-out-of-date the governing compatibility state; allow only safe stop/cancel controls and announce the alert once.
6. Replace overstated browser-abort copy with wording that does not claim durable cancellation.
7. Report cancelling, watch updates, and terminal attempt states truthfully in the primary shell status.
8. Replace non-action queued/active disabled buttons with non-interactive status content.
9. Associate blocked actions with their reason while preserving keyboard discoverability.
10. Remove the redundant parent `section` landmark.
11. Raise direct shell copy to the repository’s 12 px floor and make the watch row wrap/stack safely on narrow or enlarged layouts.
12. Disable decorative button motion for this shell when reduced motion is requested.

## Explicitly deferred

- UI-04: metric workspace density and lens presentation.
- UI-05: radar and knowledge-card visuals.
- UI-06: history retry/recovery UX and model-stage drawer visuals.
- UI-07 through UI-09: evidence import/review cards.
- Screenshot/real-browser visual approval, because the in-app browser policy currently blocks localhost automation.

## Files changed

- `frontend/src/features/model-ensemble/ModelEnsemblePanel.tsx`
- `frontend/src/features/model-ensemble/ModelEnsemblePanel.test.tsx`
- `frontend/src/features/model-ensemble/metricGuidanceSurfaces.test.tsx`
- `frontend/src/features/project-workspace/ProjectWorkspace.tsx`
- `frontend/src/features/project-workspace/ProjectWorkspace.test.tsx`
- `frontend/src/styles.css`
- this checkpoint note

## Verification record

- Focused shell, compatibility, and project integration tests: **89 passed**.
- Full frontend suite: **112 files / 1,112 tests passed**.
- TypeScript project build (`tsc -b`): **passed**.
- Production frontend build: **passed** (the existing ~515 kB main-chunk advisory remains).
- Repository privacy scan: **passed**.
- Scoped diff check: **passed**; Windows LF→CRLF notices only.
- The first bounded post-implementation audit found one same-session legacy-read race.
  Its command, watch-success, command-refusal, and watch-refusal authority paths are repaired and covered.
- Final bounded read-only audit: **PASS; no remaining reproduced P0/P1 in UI-03 scope**.
- No commit was created.

## Later visual checklist

- Desktop: heading, primary action, boundary note, watch row, and status should read in one clear order.
- 860 px breakpoint: primary action should become full width without awkward empty space.
- 360–600 px: watch copy and action should stack without horizontal overflow.
- Enlarged text: all shell copy should wrap without clipping.
- Keyboard: blocked Analyze/Watch actions should remain discoverable and explain why they cannot run; Stop must remain available for an active watch.
- Reduced motion: shell action buttons must not translate on hover.
- State tour: checking, verified empty, retrying, running, queued, cancelling, failed, partial, cancelled, definitions out of date, and retained last snapshot.
