# Checkpoint 11 handoff

Status date: 2026-08-24

Status: **Checkpoint 9C backend resilience complete locally; owner visual and
calibration review remain intentionally pending**

Checkpoint 9C closes the failure and unknown-state defects that could be
validated without reading private provider data: worker lifecycle and liveness,
startup/shutdown cleanup, onboarding counts, session-provider ownership,
model-judge catalog availability, local-model process ownership, and their
public API/UI contracts. It does not approve the visual design of UI-03 through
UI-10 and does not create human calibration evidence.

## Rollback-safe commits

| Commit | Boundary |
| --- | --- |
| `c8e3b82` | Make the durable analysis, automation, and ensemble-watch worker lifecycles failure-atomic and restartable |
| `8a4e8fa` | Preserve backend availability truth across runtime, onboarding, provider, judge, local-model, OpenAPI, and generated-client boundaries |
| `4f2056f` | Preserve nullable onboarding truth, safe error projection, and asynchronous request ownership in the UI |
| `062c92b` | Make three asynchronous UI assertions wait for the state transitions they verify |
| this documentation commit | Record Checkpoint 9C evidence and preserve the owner-review boundary |

## Accepted implementation

- The analysis, automation, ensemble-watch, and local-source refresh workers
  now publish one live generation, sanitize start/stop failures, reject a start
  while an older stopping generation is still alive, survive supervised loop
  failures where applicable, and restart after a clean or completed exit.
- Application startup registers every component before starting it, cleans up
  all registered components in reverse order, preserves the primary failure,
  and reports a fixed shutdown failure only after exhaustive cleanup. The
  authenticated runtime-liveness endpoint reports configured dead workers as
  degraded with HTTP 503; unconfigured components remain explicitly unknown.
- Onboarding preserves unknown counts as `null`, keeps exact zero distinct,
  bounds all counts to JSON-safe integers, distinguishes an unavailable or
  capped Claude transcript enumeration from an exact count, validates
  cross-field summaries, prevalidates all requested providers before granting
  consent, and bounds refresh-lock waiting.
- The onboarding and Overview UI validate exact response shapes, never add an
  unknown provider count as zero, expose only allowlisted fixed onboarding
  error codes, show loading and unavailable copy instead of a negative claim,
  and prevent an obsolete or unmounted accept request from navigating.
- Every provider-resolved analysis, model-link, ensemble, watch, and declared
  profile command now requires the exact safe session-catalog provider. Missing
  sessions return a fixed 404, catalog failure returns a fixed 503, neither path
  falls back to Codex, and overlapping domain failures remain represented by
  strict OpenAPI unions.
- Model-judge catalog failure is different from a known empty catalog. Sample
  and all-session sweeps fail closed, explicit model aliases remain usable,
  adapter errors are projected onto a closed public vocabulary, and thread
  launch failure leaves the sweep stopped and restartable rather than
  permanently running.
- Local-model status reaps dead processes, stop waits through terminate and
  kill confirmation, shutdown is exhaustive, and per-alias plus global
  generations prevent old activation, deactivation, shutdown, or remembered
  defaults from resurrecting or overwriting newer ownership.
- Three pre-existing frontend gate assertions now wait for the actual async
  trajectory, dialog, and project-title transitions. Production behavior was
  unchanged; each affected file passed three consecutive focused runs before
  the complete suite was repeated.

## Double-validation evidence

- The final independent freeze audit found four classes of release blocker:
  restart during a timed-out stop, a stuck judge sweep after thread-launch
  failure, an unsanitized async judge code, and false overlapping API response
  schemas. It also found misleading onboarding/Overview states and obsolete
  navigation. All were repaired before any implementation commit.
- Final focused gates passed **73/73 worker plus onboarding tests**, **44/44
  model-judge tests**, and **117/117 frontend onboarding, Overview, and transport
  tests twice**. Local-model lifecycle finished at 21/21, provider resolution at
  23/23 plus 66/66 adjacent API regressions, and the three timing-only test files
  each passed three consecutive runs.
- The final integrated backend slice passed **347/347 tests** with one existing
  deprecation warning. It covers onboarding, OpenAPI, provider resolution,
  judge, local models, worker/liveness, session ensemble and analysis, model
  links, declared profiles, publication, and automation.
- The ordinary frontend suite passed **115/115 files and 1,273/1,273 tests**.
  The complete synthetic browser suite passed **39/39 tests**.
- Generated OpenAPI and the TypeScript client are byte-consistent. API drift
  checking and the production TypeScript/Vite build passed with 240 modules.
- The Windows subprocess-tree security preflight passed **3/3 cases**.
  `uv lock --check`, frozen Python compilation, the repository privacy scan,
  staged and unstaged diff validation, and public/noreply commit identity checks
  passed. Windows line-ending notices were informational only.
- A new full-backend run was not started because its projected runtime still
  exceeds one hour. This checkpoint therefore does **not** claim a fresh full
  result; the prior locked baseline remains 3,416 passed with 9 platform skips.
- Overlapping dependency installers disturbed the shared development
  environment during the checkpoint. That was a test-tooling coordination
  defect, not a product worker loop. Final validation used isolated serial
  environments; the workspace runtime was then repaired serially and passed a
  clean import check.
- The application was restarted with exactly one loopback listener on
  `127.0.0.1:8765`. `/health` returned 200, and `/calibration` returned 200 for
  an HTML navigation request.

## Deferred, not lost

- UI-03 through UI-10 remain implemented but visually unapproved. The owner
  review should walk every card independently and record each mismatch before
  changing that card or its inseparable group.
- Calibration rating-save and rater-change request ownership remains a separate
  hardening slice. No representative human-reviewed holdout or product-eligible
  calibration result is claimed here.
- Local Sources and the live mini window still need route-level responsive
  coverage.
- A fresh locked full-backend run remains a later release gate; the 347-test
  integration slice is strong checkpoint evidence but is not relabelled as the
  complete repository suite.
