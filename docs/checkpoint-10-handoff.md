# Checkpoint 10 handoff

Status date: 2026-08-24

Status: **Checkpoint 9B frontend correctness complete locally; owner visual
review remains intentionally pending**

Checkpoint 9B closes the objective browser-state defects that could be
validated without judging the card designs: route metadata and focus,
asynchronous request ownership, Calibration payload validation and remote-send
confirmation, and keyboard-operable timeline controls. It does not approve the
visual design of UI-03 through UI-10 and does not change backend APIs, metric
semantics, schema 59, or the 16/0/4 release partition.

## Rollback-safe commits

| Commit | Boundary |
| --- | --- |
| `b6ee753` | Make route titles and focus ownership deterministic, including lazy and project-workspace routes |
| `4c1380a` | Serialize Local Models and Calibration work, validate Calibration payloads strictly, and use the shared confirmation dialog |
| `002f8d4` | Add accessible timeline zoom, pan, reset, keyboard, and status controls |
| `7a8fd6e` | Bound frontend test workers so the ordinary quality command is stable on high-core hosts |
| this documentation commit | Record Checkpoint 9B evidence and preserve the visual-review boundary |

## Accepted implementation

- Every routed screen now owns an exact `<Route> · Prompt Enhancer` document
  title. A genuine client-side route change focuses `#main-content` after the
  route owner exists; an initial direct load does not steal focus.
- Lazy routes retain pending focus across loading. Project-workspace and quality
  profile routes delegate focus only when their detailed owner can actually
  render, so a loading or truncated route cannot consume the focus request.
- Local Models uses explicit generation and context ownership. Polls are
  serialized, a manual reload retires the previous poll, stale completions
  cannot replace current state, and transport changes or unmounts abort or
  ignore obsolete work.
- Calibration rejects malformed samples and members before rendering them. The
  parser validates known metric keys, metric subsets, unique positions and
  sessions, provider values, timezone-aware RFC 3339 timestamps, pseudonyms,
  Unicode code-point bounds, and nullable or absent display labels.
- Calibration judge and allowance commands own their 15-second polling window.
  A command supersedes its older poll, an older poll cannot supersede a pending
  command, and context or transport changes clear stale completed state.
- Remote Calibration submission uses the shared accessible dialog. Cancel has
  initial focus, focus is trapped and restored, Escape cancels, the destination
  and privacy boundary are explicit, and no remote request starts before the
  user chooses **Send**.
- The session timeline exposes visible Zoom in, Zoom out, Earlier, Later, and
  Full timeline controls with truthful disabled boundaries. The chart also
  supports `+`, `-`, arrow keys, and Home, announces its visible range, and uses
  the same minimum span for pointer and keyboard input.
- Vitest uses at most four workers. This prevents unrelated JSDOM interaction
  tests from being starved by unbounded high-core fan-out while preserving the
  ordinary `npm test` command as the quality gate.

## Double-validation evidence

- Independent reciprocal reviews approved route/focus behavior, Local Models,
  Calibration and dialog behavior, and the timeline controls. Focused final
  checks passed 2/2 route regressions, 16/16 Local Models cases, 15/15
  Calibration plus dialog cases, and 5/5 timeline cases.
- The ordinary frontend suite passed **115/115 files and 1,252/1,252 tests**
  with the committed worker bound.
- Generated API drift checking and the production TypeScript/Vite build passed.
  The existing 523.47 kB main-chunk advisory remains non-blocking.
- The complete synthetic browser suite passed **39/39 tests**, including
  click navigation, browser Back, title, focus, standalone-route, mobile, and
  keyboard coverage. Its temporary test server shut down cleanly.
- `uv lock --check`, frozen Python compilation, the privacy scan, and diff
  validation passed. Windows line-ending notices were informational only.
- No backend production or API source changed. A fresh full backend run was
  stopped at 4% with no failures because its projected runtime exceeded an
  hour; this checkpoint does **not** claim a new full-backend result. The prior
  locked result remains 3,416 passed with 9 platform skips.
- The application was restarted with exactly one loopback listener on
  `127.0.0.1:8765`, and `/health` returned 200. A privacy-safe live-browser pass
  confirmed Overview → Sessions, browser Back, Models, and Calibration titles,
  headings, and navigation focus. A direct Overview load did not steal focus.
  The deliverable tab was returned to `/calibration`.

## Deferred, not lost

- Checkpoint 9C owns backend resilience: failure-atomic worker lifecycle,
  component liveness, unknown-versus-zero onboarding truth, fail-closed session
  provider resolution, and unavailable model-judge catalog handling.
- Calibration rating-save and rater-change request ownership remains a separate
  hardening slice; it was pre-existing and is not hidden by this checkpoint.
- Local Sources and the live mini window still need route-level responsive
  coverage.
- UI-03 through UI-10 remain implemented but visually unapproved. The later
  owner review should walk each card independently, reproduce any defect in the
  rendered app, and then repair only that card or inseparable card group.
