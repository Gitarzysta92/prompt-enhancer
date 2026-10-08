# Checkpoint 12 handoff

Status date: 2026-08-25

Status: **Checkpoint 9D code-only cross-surface audit and repair complete;
owner card-by-card visual review remains pending**

This checkpoint performed the requested broad review before the next product
slice. It repaired objective correctness, privacy, accessibility, concurrency,
metric-provenance, and UI-state defects across the current application. It does
not visually approve UI-03 through UI-20 and does not create human calibration
evidence.

## Bounded external review ledger

- Exactly **20** isolated Claude CLI review invocations used the requested
  `claude-opus-5` model at `max` effort against one immutable code-only
  snapshot. Tools were restricted to read/search operations.
- **9** reviews returned accepted structured verdicts. **11** reached their
  execution cap without a verdict; capped runs are recorded as no-verdict, not
  as approvals. No run was retried and no twenty-first reviewer was started.
- The accepted reviews produced **21** unique candidates. Independent local
  verification classified **17 defects** and **4 design enhancements**; none
  was dismissed without checking the current source and tests.
- The external-review spend was **$17.70**, below the announced $20 ceiling.
- No real provider session, prompt, transcript, tool output, credential,
  runtime database, local configuration, or derived private metric was read or
  sent to a reviewer. The snapshot contained repository code and synthetic
  fixtures only.

## Accepted repairs

- Model-judge windows are canonical JSON marked as untrusted evidence. They
  retain the earliest task-defining user request plus a recent bounded tail,
  fail closed when a meaningful anchor cannot fit, reject extra output keys,
  and persist distinct normal and reduced-context prompt profiles.
- Judge-sweep reuse now requires all expected labels, a current prompt profile,
  the exact active model identity, and the current sealed source-window
  fingerprint. Partial or stale judgments are re-evaluated rather than treated
  as complete.
- Claude hook receipt time is now `receiver_observed`, distinct from
  provider-reported telemetry. Database migration 60 preserves populated v59
  events and their child evidence, adds the new closed time-basis value, and
  keeps old provenance unchanged. The affected data-quality metric definitions
  and packs have new versions.
- Remote annotation has an authenticated, read-only pre-send disclosure for
  the exact destination, retained redacted data, raw-transcript exclusion,
  configured-active-at-submission policy, and current model alias. Sending is
  disabled when that contract is unavailable, malformed, or lacks an active
  model; the UI can recheck after a model is activated.
- The application shell has distinct semantic icons for every primary route,
  one status announcement, shared truthful loading/empty/error states, a
  stricter modal focus trap, and keyboard-complete research tabs with stable
  tab/panel relationships.
- Loading, unavailable, empty, failed, and stale states are now distinct across
  Discovery, Local Sources, Overview, stored Prompt checks, and onboarding.
  Abort/generation ownership prevents older responses from overwriting newer
  navigation, filters, runtime transports, or transfer resets.
- Prompt charts use a consistent quality orientation for lower-is-better
  metrics while disclosing raw direction. Hardware/model copy no longer claims
  machine-specific fit or throughput without measurements. Presence and direct
  transfer controls retain and release state predictably.
- Claude consent responses must satisfy the requested grant/revoke
  postcondition and the complete exact content-free status contract before the
  UI shows success.
- The locked development dependency set now includes the lightweight Hub
  client required by the mandatory public-only download test, so a clean
  documented dev environment exercises that boundary instead of failing at
  import time.

## Freeze review and validation

The first implementation review found **15 additional integration defects**
across backend and frontend ownership boundaries. This included one consent
disclosure regression introduced by the first repair pass. Every finding was
fixed and given a deterministic regression before the tree was frozen.

- Complete backend: **3,585 passed, 9 expected Windows symlink skips**, with one
  existing Starlette deprecation warning.
- Complete frontend: **115/115 files, 1,301/1,301 tests** after a clean
  `npm ci`; TypeScript and the production Vite build passed.
- Synthetic browser suite: **39/39** Chromium tests. The separate local-real
  suite was intentionally not run because it can read owner data.
- Schema-v60 migration/sentinel slice: **67/67**. Hardened judge integration:
  **65/65**. Windows subprocess-tree security preflight: **3/3**.
- OpenAPI is byte-exact to the runtime schema, the generated TypeScript client
  has no drift, the frozen dependency lock and Python compilation pass, and the
  repository privacy scanner passes.
- The application was restarted with exactly one listener on
  `127.0.0.1:8765`; `/health` and `/calibration` returned HTTP 200. A
  privacy-safe in-app browser check confirmed one main region, all 15 primary
  navigation icons structurally distinct, and remote annotation disabled when
  no active model was disclosed. The validated Calibration tab was left open
  for the owner's later review.

Two stopped full-suite attempts are part of the evidence, not hidden retries:
the first exposed the missing dev-only Hub dependency at 35%; the second
exposed OpenAPI generation racing a concurrent implementation agent at 54%.
After the exact failures were repaired, all implementation agents were stopped,
the tree and generated artifacts were frozen, and the single frozen full run
passed. This ordering prevents the concurrent-edit validation loop that had
previously burned time without producing a trustworthy checkpoint.

## Deferred, not lost

- UI-03 through UI-20 still require the owner's visual card-by-card review in
  the order tracked by `ui-card-review-backlog.md`.
- Human calibration ratings, rater-change ownership, and representative
  holdout evidence remain separate product work; this checkpoint does not
  promote any model judgment into objective metric truth.
- Prompt-injection hardening reduces role/format spoofing but cannot make an
  arbitrary model immune to adversarial evidence. Model judgments remain
  non-authoritative and objective verification evidence still outranks them.
