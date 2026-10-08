# Checkpoint 8 handoff

Status date: 2026-08-24

Status: **Checkpoint 7B complete; locked gates, commit inventory, and loopback
reload verified**

This handoff records the Checkpoint 7B implementation slice as Checkpoint 8:
the exact M58 requirement-verification revision is now atomically bound to each
new live r8 model-ensemble publication. Work was split across application,
persistence, API/frontend, and adversarial lanes, followed by reciprocal
read-only review.

## Stable state

- Branch: `codex/real-metrics-campaign`
- Baseline: `8d521ee` (accepted Checkpoint 7 handoff)
- Database schema: 59; migrations 1-58 remain byte-frozen
- Canonical measured projection: `metric-contract-v2-projection-8`
- Readiness catalog: `metric-evidence-readiness-v2-7`
- Operability catalog: `metric-operability-v4`
- Release inventory: 16 shipped conditional paths, 0 task-profile gaps,
  4 provider/extractor or release-composition gaps, and 0 model-authoritative
  measured metrics
- Local service: one loopback-only listener on `127.0.0.1:8765`; `/` and
  `/health` returned HTTP 200 after the final reload
- OpenAPI and generated TypeScript synchronization: verified under the locked
  repository runtimes

## Rollback-safe commits

| Commit | Boundary |
| --- | --- |
| `5c8d49c` | M59 atomic verification binding, r8 projection, persistence, and focused tests |
| `57b8086` | HTTP/frontend contract synchronization and adversarial integration coverage |
| `38c5552` | WP-25, campaign inventory, and Checkpoint 8 handoff |
| this follow-up commit | `/calibration` validation correction and strict SPA/static routing hardening |

## Accepted implementation results

### Exact durable run authority

- M59 appends a strict, content-free verification-binding table plus dedicated
  r8 state and publication-seal tables. M58 and r1-r7 publication history are
  not rewritten or reinterpreted.
- Every r8 run records one closed source partition: `unavailable`,
  `opportunity_bound_exceeded`, `awaiting_evidence`, or `persisted_evidence`.
- Persisted authority includes the exact r6 identities, opportunity set,
  evidence set, through-revision, current-head/result/acceptance/resolution/met
  counts, and all issuer/schema/policy/projection versions.
- The binding fingerprint is installation-keyed and semantic; the UTC bound
  time is recorded but deliberately excluded from run semantics.
- Revision zero is valid for a sealed opportunity set with no authority heads.
  Missing evidence stays nonnumeric and never becomes zero or failure.

### Atomicity, restart, and history

- The live service resolves M58 read-only before inference and never issues an
  opportunity set as a model-run side effect.
- Save revalidates the exact current M58 head inside the same `BEGIN IMMEDIATE`
  transaction as the run, binding, twenty r8 states, typed receipts, and seal.
- Append-first ordering rejects the stale save and rolls back the whole graph.
  Save-first ordering preserves the historical revision and permits the later
  append after the writer lock is released.
- Historical persisted prefixes and historical `awaiting_evidence` markers
  remain readable after legitimate later evidence changes and after restart.
- Different verification revisions produce distinct identities and are
  conservatively incomparable; exact same-revision replay may reuse the run.
- Objective-result observations must strictly advance along their predecessor
  chain, with both future-write SQL enforcement and historical read validation.

### Live r8 metric truth

- R8 preserves nineteen r7 metric states and replaces only
  `outcome.verified_requirement_coverage` through objective projection v4.
- The exact reviewed r6 active-requirement set owns the denominator. Only
  current app-issued objective results or separately typed owned-native
  acceptance authority can resolve an opportunity.
- Partial and unknown evidence remains nonnumeric with explicit bounds; a fully
  resolved non-empty set may be known; an empty reviewed set is
  `not_applicable`.
- Every r8 publication seals all twenty typed receipts. The verified-
  requirement row must carry the exact v4 engine, algorithm, version, and
  no-rubric provenance on save and hydration.
- Native acceptance is never mislabeled as an objective verifier receipt in
  readiness or help text.

### Persistence, tamper, and privacy

- R8 and legacy publication identities cannot coexist on one run in either
  insertion order.
- Keyed binding substitution, stale heads, foreign r6/M58 authority, missing
  seals, forged verified counts, incomplete nineteen-row graphs, malformed
  history, and ordinary-hash recomputation fail closed.
- Direct updates and child deletes are rejected. Owning-run deletion removes
  its r8 sidecars without erasing independently owned M58 evidence; owning
  session/source deletion cascades the complete derived graph.
- Stored and public r8 data remains content-free and uses only synthetic
  fixtures in verification.

### API and frontend consistency

- The public run DTO exposes a minimized binding without session/window or
  server-time fields.
- R1-r7 responses retain a null verification binding; r8 responses require the
  closed, bounded binding shape.
- Checked OpenAPI and generated TypeScript identities are synchronized with
  schema 59, r8, readiness v2-7, and operability v4.
- Workspace operability, evidence readiness, help text, and binding parsers use
  the same catalog identities and reject malformed sources or out-of-bound
  counts.
- This checkpoint does not approve a card-layout redesign. UI-03 through UI-10
  remain queued for the later card-by-card visual pass requested by the owner.

## Cross-review defects caught before the final gate

1. Historical `awaiting_evidence` hydration originally rechecked present-day
   absence, so later legitimate opportunity issuance invalidated the old run.
2. The first r8 persistence contract did not require all twenty typed receipts
   or the exact v4 provenance for the verified-requirement typed row.
3. A reviewed r6 plan with no composed verification reader correctly produced
   an `unavailable` fallback in the application but was rejected by the SQL and
   repository authority checks.
4. UI operability and help routing initially retained older r7/catalog
   assumptions, making current status text internally inconsistent.
5. Frontend binding parsers initially missed some closed-source and persisted-
   count storage bounds.
6. The minimized API binding, checked OpenAPI, and generated TypeScript client
   drifted while parallel lanes were landing.
7. The first locked full-suite run exposed a stale checked OpenAPI artifact and
   two frozen-schema compatibility helpers that still stopped at M58. The
   artifact was regenerated under the repository runtime and the helpers were
   advanced to M59 without changing historical migration meaning.
8. The final diff audit found current-path comments that still described r8
   behavior as r7-only and a shared frontend readiness fixture that stopped at
   r7. Wording was corrected without changing production behavior, and a
   four-case r8/readiness-v2-7 truth table now covers unavailable, awaiting,
   partial persisted, and fully resolved evidence while refusing to invent a
   typed-verification contributor.

The final implementation must retain one focused synthetic regression for each
repair.

## Final verification evidence

- Full locked backend suite: **3,416 passed, 9 platform-skipped, 0 failed** in
  27m28s. The only warning is the existing Starlette/httpx deprecation notice.
- Full frontend suite: **115/115 files and 1,234/1,234 tests passed** in the
  final no-contention run.
- Focused Checkpoint 8 application/persistence/API/frontend gates passed: the
  final combined backend slice passed 109 tests, the post-audit backend slice
  passed 85, the root frontend slice passed 203, and the post-audit frontend
  slice passed 153. The independently reviewed readiness file passed 18 tests.
- Migration freeze, rollback, and schema compatibility passed, including 4/4
  M59 migration tests, 26 r8 persistence tests, and 27 legacy persistence
  tests.
- Two-connection ordering, restart, historical hydration, privacy deletion,
  and tamper coverage passed in the r8 persistence and two live E2E tests.
- Generated TypeScript checking and the production frontend build passed. Vite
  retains its advisory main-chunk warning at 523.15 kB (133.39 kB gzip).
- The checked OpenAPI byte-exact test and generated-client drift check passed
  under the repository `.venv` and Node toolchain.
- Python compilation, the repository privacy scan, and diff validation passed;
  only non-semantic Windows LF-to-CRLF notices were emitted.
- The verified repository service was reloaded hidden. Exactly one listener
  remained on `127.0.0.1:8765`; `/` and `/health` returned HTTP 200.

## Post-handoff routing validation and static-boundary correction

- The first command-line `/calibration` probe omitted a browser navigation
  `Accept: text/html` header and therefore received the intentionally strict
  generic-client 404. It did not reproduce a browser refresh.
- A browser-shaped GET and HEAD both return the SPA shell with HTTP 200, and an
  actual in-app browser reload stayed on `/calibration` and rendered the
  Calibration page. The generic `Accept: */*` request remains HTTP 404 by
  design, so arbitrary clients cannot turn an allowlisted history path into an
  HTML response accidentally.
- The follow-up adversarial review found three adjacent pre-existing boundary
  defects: Starlette could normalize an encoded `assets/../index.html` alias
  before the SPA allowlist, bare `/live` was server-allowlisted although the
  frontend owns only `/live/projects/<pseudonym>`, and HTML Accept matching did
  not honor case or `q=0` quality.
- Static paths are now lexically rejected before file resolution when they
  contain empty, dot, dot-dot, backslash, or control-character segments. The
  bare `/live` aliases are no longer navigation routes. HTML fallback now
  requires an exact, case-insensitive `text/html` media range with positive,
  valid quality. Valid static assets, the root shell, trailing-slash client
  routes, reserved APIs, and JSON health behavior remain unchanged.
- The static-hosting regression pins `/calibration` and `/calibration/` across
  browser GET/HEAD and generic-client behavior, encoded and double-encoded
  traversal variants, Accept quality, bare `/live`, and POST/PUT/PATCH/DELETE/
  OPTIONS non-shell behavior. The focused backend routing/API gate passed 46
  tests and the frontend route gate passed 30 tests.

## Accepted non-blocking limitations

- The release partition remains 16/0/4; durable verification authority is not
  evidence that every production provider supplies the required source facts.
- All local model estimates remain experimental, uncalibrated, and
  product-ineligible. No model authors a measured metric.
- Native acceptance is a valid explicit authority but is not an objective test
  receipt and must remain labeled separately.
- User visual review of UI-03 through UI-10 remains pending.

## Next dependency-safe trajectory

1. Review the canonical quality-profile surroundings and navigation hierarchy.
2. Walk UI-03 through UI-10 card by card on localhost, recording each approved
   visual/interaction repair as a separate checkpoint.
3. Do not change the 16/0/4 release inventory without new production-provider
   evidence and an explicit operability review.
