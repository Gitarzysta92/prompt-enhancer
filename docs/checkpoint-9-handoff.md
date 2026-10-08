# Checkpoint 9 handoff

Status date: 2026-08-24

Status: **Checkpoint 9A complete locally; first hosted CI execution awaits a
push or pull request**

Checkpoint 9A converts the repository's manual verification inventory into a
locked, privacy-safe release gate and closes the objective standalone-route
defects exposed while adding that gate. It does not change schema 59, the r8
metric projection, readiness/operability semantics, or the 16/0/4 release
partition.

## Rollback-safe commits

| Commit | Boundary |
| --- | --- |
| `9e16be1` | Preserve the labelled Models page and heading in loading, unavailable, error, and ready states |
| `dd035ad` | Correct 16/0/4 browser truth, add mobile standalone-route coverage, and remove one evidence-test render race |
| `1566741` | Add the locked Windows/Linux CI quality gate and its contributor documentation |
| this documentation commit | Record Checkpoint 9A evidence and update the visual-review backlog |

## Accepted implementation

- Research browser coverage now requires the current twenty-metric partition:
  sixteen shipped paths, zero task-profile gaps, four provider/extractor gaps,
  and zero model-authored measured metrics.
- Synthetic Chromium exercises Overview, Sessions, Calibration, and Models at
  360 px. It requires each route's active navigation, title trail, main region,
  page heading, and no document overflow, plus genuine Tab traversal, visible
  focus, and Enter-key navigation.
- The Models page uses one labelled header boundary in every load state. A 404
  or invalid response no longer removes the route's `h1`.
- The requirement-action mismatch regression waits for the user-visible native
  confirmation control's React commit. It retains the mismatch alert and the
  guarantee that no evidence-change callback fires; no sleep or timeout
  inflation was introduced.
- GitHub Actions runs repository integrity, full backend suites on Ubuntu and
  Windows, platform-owned zero-skip security preflights, and the locked
  frontend unit/API/build/Playwright gate.
- Workflow permissions are read-only. Checkout credentials are not persisted,
  action revisions are pinned to immutable commits, Python uses the committed
  `uv.lock` in frozen mode, and no test/runtime artifacts or secrets are
  uploaded.

## Verification evidence

- Final frontend suite: **115/115 files and 1,237/1,237 tests passed**.
- Final synthetic browser suite: **38/38 tests passed**. The changed Research
  and standalone-route group passed 7/7.
- Models state coverage passed 12/12. The previously timing-sensitive
  requirement-action case passed 20/20 independent stress iterations and its
  complete file passed 34/34.
- Generated API drift and the production TypeScript/Vite build passed. The
  existing 523.15 kB main-chunk advisory remains non-blocking.
- The focused routing plus Windows taskkill boundary gate passed 24/24; the
  platform-owned Windows subset contributed 3 passes and zero skips.
- `uv lock --check`, frozen-sync dry-run, Python compilation, workflow security
  assertions, immutable action-tag verification, the privacy scan, and diff
  validation passed. Windows line-ending notices were informational only.
- No backend production source changed. The prior locked backend result remains
  3,416 passed and 9 platform-skipped; the new hosted workflow will execute the
  complete backend suite on both Windows and Linux after the next push or pull
  request. This handoff does not claim a hosted green run before that event.
- The loopback service was rebuilt and reloaded with exactly one listener on
  `127.0.0.1:8765`; `/health` returned 200. Targeted in-app browser checks
  confirmed the Models and Calibration `h1` boundaries, then returned the
  deliverable tab to `/calibration`.

## Deferred, not lost

- Checkpoint 9B owns objective frontend correctness: route title/focus policy,
  serialized Local Models and Calibration polling, strict Calibration payload
  parsing, proper confirmation-dialog semantics, and keyboard timeline zoom.
- Checkpoint 9C owns backend resilience: failure-atomic worker lifecycle,
  component liveness, unknown-versus-zero onboarding truth, fail-closed session
  provider resolution, and unavailable model-judge catalog handling.
- Local Sources and the live mini window still need route-level responsive
  coverage. UI-03 through UI-10 still need the owner's later visual review;
  Checkpoint 9A does not approve a card redesign.
