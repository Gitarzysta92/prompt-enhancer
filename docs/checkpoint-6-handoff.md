# Checkpoint 6 handoff

Status date: 2026-08-24

This handoff closes the third bounded implementation wave: verified requirement
evidence foundation, the Claude Code hooks r7 provider boundary, and UI-10
quality-profile truth and context. Every implementation lane was owned by one
agent and independently attacked by another before acceptance.

## Stable state

- Branch: `codex/real-metrics-campaign`
- Wave baseline: `378781f` (`docs(ui): record wave two checkpoint status`)
- Database schema: 57; no migration was added or rewritten
- Current operability catalog: 16 operable, 0 model-authoritative measured,
  4 provider-adapter-required
- Local service: loopback-only; root page returned HTTP 200 after final build
- OpenAPI artifact: unchanged and byte-exact under the locked project runtime

## Rollback-safe commits

| Commit | Boundary |
| --- | --- |
| `8b06551` | Verified requirement-evidence authority and objective v4 projection |
| `32b2e61` | Atomic Claude hooks/telemetry read boundary and truthful r7 readiness ceiling |
| `2326f00` | UI-10 quality profile, exact board/radar hierarchy, and guarded dialogs |
| `227fb73` | UI-09 review-effect test synchronization; no production change |
| `f2552c4` | Deterministic MCP subprocess test import path; no production change |
| `4781413` | Fail-closed Windows accelerator cleanup proofs; no production change |

## Accepted implementation results

### Verified requirement evidence

- Issues a versioned, content-free opportunity bound to the exact ordered set of
  native-reviewed active r6 requirements.
- Keeps objective PASS/FAIL/UNKNOWN separate from owned-native
  ACCEPTED/REJECTED/UNKNOWN.
- Rejects missing, duplicate, foreign, model-authored, assistant-authored, and
  tampered evidence.
- Overrides only `outcome.verified_requirement_coverage` in objective projection
  v4 and preserves right-censored unknowns.
- Does not add persistence, HTTP/API exposure, live r8 wiring, or an operability
  promotion. Those remain a later checkpoint.

### Claude hooks provider boundary

- Reads admitted hook rows and joined telemetry from one atomic SQLite snapshot.
- Binds dense admitted order, count, session/project ownership, provenance route,
  content-free action descriptors, and one boundary commitment.
- Rejects rebound telemetry summary or nested-counter identities even when an
  attacker recomputes the boundary fingerprint.
- Reconciles only the documented missing-cwd project placeholder for the exact
  already-pseudonymized provider session, in either ingestion order and across
  restart; unrelated and conflicting non-placeholder identities fail closed.
- Missing telemetry keeps token usage UNKNOWN rather than zero or supported.
- Status remains **PARTIAL** and `release_ready=false`. Complete delivery and
  same-read ephemeral descriptor retention are still unproven; operability
  remains 16/0/4.

### UI-10 quality profile

- Makes the exact metric board authoritative and places the direction-safe radar
  second, with no composite score and no lower-is-better review-load axes.
- Resets same-kind A→B profile, pin, readiness, and dialog state by exact owner.
- Withholds readiness unless session, preset, profile, pack, version, and current
  provider context all match.
- Strictly bounds malformed prop reports before access; null/object/null-row
  payloads cannot throw, display zero, or produce verified metadata.
- Captures analyze/share handlers at open time, aborts or epoch-guards delayed
  work, and preserves focus trap, Escape, connected-opener restoration, unique
  IDs, forced colors, reduced motion, and narrow-layout behavior.
- User visual review remains pending for UI-03 through UI-10.

## Cross-review defects caught before commit

1. Provider validation originally accepted foreign telemetry summary/counter
   identity after a recomputed fingerprint. Four synthetic rebound attacks
   reproduced red before the identity checks were repaired.
2. UI-10 originally accepted foreign pack/preset/provider readiness and crashed
   on `metrics=null`. Seven red regressions plus a positive exact-owner control
   drove the fail-closed repair.
3. Two UI-09 tests clicked acknowledgement before the review's passive reset
   effect settled. Production authority behavior was sound; the tests now wait
   for the exact review-open handshake.
4. A global Python run falsely reported OpenAPI drift because it used older
   FastAPI/Pydantic versions. The locked runtime proved zero semantic and byte
   differences, so the artifact was not regenerated.
5. An attempted Windows cleanup repair inferred tree death from a nonzero
   `taskkill` result plus root exit. Independent review produced a surviving
   grandchild counterexample and blocked it. Production was restored unchanged;
   the final tests preserve rc=0-only confirmation, prove cleanup-unconfirmed
   becomes typed UNKNOWN, and require root and descendant markers to stay absent.

## Final release evidence

- Locked Python repository suite: **3,335 passed, 9 platform-skipped, 0 failed**
  across 3,344 collected tests in 45m09s.
- Frontend repository suite: **114 files / 1,219 tests passed**.
- UI-10: **90 direct**, **131 feature**, and **30 host** tests passed, followed
  by an independent frozen-tree PASS.
- Provider: **62 focused** and **141 affected** tests passed, followed by an
  independent rebound/reconciliation PASS.
- Verified requirement foundation: **180 independent affected tests passed**.
- TypeScript project check and production frontend build: passed.
- Privacy scanner and diff validation: passed; Windows LF-to-CRLF notices only.
- Local root page: HTTP 200, `text/html; charset=utf-8`.
- Nothing from a real provider session, transcript, credential, browser page, or
  private local source was inspected or copied into tests or documentation.

## Accepted non-blocking limitations

- Claude hooks r7 remains PARTIAL for the two explicit provider-proof blockers.
- The main frontend chunk is 514.99 kB minified, above Vite's advisory threshold.
- One Starlette/httpx deprecation warning remains in the locked Python runtime.
- Nine symlink-capability tests are skipped on this Windows environment.
- Component and integration tests do not replace the pending user visual review.

## Next dependency-safe trajectory

1. **Objective coverage integration:** append any required migration rather than
   editing schema 57; persist the verified-requirement opportunity/evidence,
   expose only content-free typed contracts, and wire the live projection without
   promoting readiness.
2. **Synthetic end-to-end authority tour:** prove r6 reviewed requirements to
   issued evidence to owned-native decision to objective coverage, including
   restart, stale owner, tampering, and right-censored unknowns.
3. **UI-11 session surroundings:** review the session radar/timeline/coaching and
   model-link hierarchy around the now-frozen canonical quality profile.
4. **User visual pass:** walk UI-03 through UI-10 card by card on localhost at the
   recorded viewport/theme/state matrix, fixing only one approved card slice at a
   time.
