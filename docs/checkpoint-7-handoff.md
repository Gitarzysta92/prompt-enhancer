# Checkpoint 7 handoff

Status date: 2026-08-24

This handoff closes Checkpoint 7A: durable requirement-verification evidence
and its local API. Implementation was split across persistence, HTTP, and
end-to-end lanes, then each boundary received an independent read-only review.
Live objective-projection activation remains a separate Checkpoint 7B.

## Stable state

- Branch: `codex/real-metrics-campaign`
- Baseline: `f38a390` (`docs(checkpoint): record wave three handoff`)
- Database schema: 58; migrations 1-57 remain frozen
- Current operability catalog: 16 operable, 0 model-authoritative measured,
  4 provider-adapter-required
- Local service: loopback-only on `127.0.0.1:8765`; root and `/health` returned
  HTTP 200 after the final reload
- OpenAPI and generated TypeScript client: synchronized under the locked
  project runtimes

## Rollback-safe commits

| Commit | Boundary |
| --- | --- |
| `b38dd55` | M58 durable verification authority, local API, generated contracts, synthetic tests, and WP-24 |
| `c4fa80d` | Test-only synchronization for two pre-existing UI evidence effects |

## Accepted implementation results

### Durable authority

- M58 appends six strict, content-free tables without rewriting M1-M57.
- Current opportunity sets are deterministically issued from the exact sealed
  r6 requirement-plan authority and remain rehydratable after restart.
- Objective PASS/FAIL/UNKNOWN results and owned-native
  ACCEPTED/REJECTED/UNKNOWN decisions remain separately typed.
- Writes enforce dense revisions, exact predecessors, immutable seals,
  session ownership, keyed identities, current-head checks, and exact
  idempotent replay.
- Missing seals, stale sources, foreign ownership, malformed versions,
  recomputed identities, direct-SQL tampering, and authority-kind switching
  fail closed.
- Session and source-run privacy deletion cascade through the graph; direct
  child deletion remains blocked.

### Local HTTP boundary

- Adds current issuance, historical snapshot, objective-result append, and
  native-acceptance endpoints beneath the owning session.
- Issuance, reads, and objective results require local authentication.
- Native acceptance rejects API tokens and Bearer credentials and requires the
  ephemeral browser cookie, exact Origin, CSRF proof, a one-shot path/body-bound
  user-presence capability, and the closed confirmation literal.
- Responses are content-free and private/no-store. Sanitized runtime error
  bodies match their published 401/403/404/409/422/503 OpenAPI schemas.

### Deliberate non-change

- The live model-ensemble pipeline does not call objective projection v4 yet.
- Readiness, operability, the 16/0/4 release partition, and r7 history are
  unchanged.
- An assistant completion claim, model judgment, or client-minted pass/fail
  value is still not verification evidence.

## Cross-review defects caught before commit

1. Idempotent replay initially included a fresh server timestamp, so a valid
   retry conflicted instead of returning the original record.
2. Current authority initially depended on ephemeral review state and could not
   rehydrate from a fresh process.
3. One SQL guard confused source ordinals with keyed-identifier sort order.
4. The acceptance path was initially absent from the exact user-presence
   allowlist.
5. The first generated acceptance contract advertised token-style security and
   omitted its real browser-cookie and Origin requirements.
6. Published error DTOs initially differed from sanitized runtime responses;
   the final cross-origin case exposed one remaining `origin not allowed`
   literal mismatch.
7. Mechanical current-schema assertions and the synthetic v55 downgrade helper
   required bounded updates for M58 while preserving historical M57 meaning.
8. A source-run privacy cascade was blocked while its owning session remained;
   the trigger now permits only the intended parent-authorized cascade.
9. The end-to-end database canary scan was narrowed to the exact database,
   WAL, and SHM files so it cannot inspect unrelated paths.
10. Two existing frontend tests raced passive focus/reset effects. Only their
    synchronization changed; production UI behavior did not.

## Final verification evidence

- Full locked backend suite: **3,366 passed, 9 platform-skipped, 0 failed**.
- Full frontend suite: **114 files / 1,219 tests passed**.
- Locked focused Checkpoint 7A gate: **65 passed**.
- Independent core/migration review gate: **50 passed**.
- Post-repair API/bootstrap/OpenAPI/user-presence gate: **15 passed**; the exact
  cross-origin regression independently passed again.
- The schema-compatibility audit covered 436 unique cases, including the
  corrected synthetic-downgrade node.
- TypeScript checking, production frontend build, API drift checking, Python
  compilation, privacy scanning, and diff validation passed.
- The only backend warning is the existing Starlette/httpx deprecation notice;
  Windows line-ending notices are non-semantic.
- No real provider session, transcript, credential, private browser content, or
  unrelated local file was read or copied into the implementation or tests.

## Accepted non-blocking limitations

- M58 does not prove which evidence revision was sealed into a particular
  model-ensemble run.
- The main frontend chunk remains 514.99 kB minified, above Vite's advisory
  threshold.
- Nine symlink-capability tests remain skipped on this Windows environment.
- The user visual review of UI-03 through UI-10 remains pending.

## Next dependency-safe trajectory

1. **Checkpoint 7B — atomic run binding:** append a new migration that seals
   the exact opportunity set, evidence set, through-revision, r6 identities,
   and relevant versions into each model run.
2. **7B adversarial validation:** prove restart, stale-head, tamper, rollback,
   concurrency, and run-reuse behavior before enabling objective projection v4.
3. **UI-11 surroundings:** review the session radar, timeline, coaching, and
   model-link hierarchy around the canonical quality profile.
4. **Card-by-card visual pass:** inspect UI-03 through UI-10 on localhost and
   repair one explicitly approved card slice at a time.
