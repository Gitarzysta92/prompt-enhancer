# WP-25: Requirement-verification run binding and live r8 projection

Status: **Checkpoint 7B complete; locked repository gates and the loopback
root/health reload are verified**

## Outcome

This work package closes the durability gap left by WP-24. A live
model-ensemble run now records the exact immutable M58 requirement-verification
revision used to project `outcome.verified_requirement_coverage`. Restart,
history, reuse, and trajectory readers no longer have to infer which evidence
head a run observed.

The live path remains local and content-free:

1. resolve the exact reviewed r6 requirement-plan authority for the selected
   sealed source window;
2. derive the deterministic requirement-verification opportunity identity;
3. read, but never auto-issue, the current M58 evidence snapshot;
4. bind one closed source partition and its exact authority identity into the
   run request before inference;
5. project all twenty metrics under append-only projection r8, replacing only
   verified-requirement coverage with objective projection v4; and
6. revalidate the M58 head and atomically seal the run, binding, twenty r8
   states, typed receipts, and publication under one `BEGIN IMMEDIATE`
   transaction.

Assistant completion claims, model judgments, action-completion states, and
client-minted pass/fail values remain outside this authority boundary.

## Closed source partitions

Every r8 run carries exactly one content-free verification source:

- `unavailable`: the verification capability or reviewed authority is not
  composed for this run; no requirement or evidence identity is invented;
- `opportunity_bound_exceeded`: the exact reviewed requirement set exceeds the
  bounded receipt contract, so the metric remains nonnumeric;
- `awaiting_evidence`: the reviewed opportunity identity exists, but no M58 set
  had been issued at the run's atomic save boundary; and
- `persisted_evidence`: an exact M58 opportunity set and evidence prefix were
  used, including revision zero when the sealed set has no authority heads.

Missing evidence remains unknown or pending. It is never converted to zero,
failure, rejection, or a completion claim. Native explicit acceptance remains
a separately typed authority and is not described as an objective verifier
receipt.

## M59 append-only storage boundary

Migration 59 appends three strict tables after byte-frozen migrations 1-58:

- `session_model_ensemble_requirement_verification_bindings`;
- `session_model_ensemble_metric_states_v2_r8`; and
- `session_model_ensemble_metric_publication_v2_seals_r8`.

The binding stores only pseudonymous session/window identity, exact r6
confirmation/proposal/fingerprint/version identity where applicable,
opportunity- and evidence-set fingerprints, through-revision, bounded head and
outcome counts, issuer/schema/policy/projection versions, one UTC server time,
and local/content flags. Its semantic fingerprint is installation-keyed and
excludes only the non-semantic observation time. No prompt, transcript, path,
provider payload, tool output, proof prose, or assistant/model claim is stored.

R8 is a new publication identity. R1-r7 rows remain readable under their
original tables and meanings, and SQL guards reject mixing a legacy and r8
publication on the same run in either insertion order. R8 seals require the
complete twenty-state publication, all inherited profile/r6/r7 bindings, the
exact requirement-verification binding, all twenty typed metric receipts, and
the reviewed v4 provenance for the verified-requirement typed row.

## Live verified-requirement projection

`metric-contract-v2-projection-8` inherits the nineteen unchanged r7 metric
states. Only `outcome.verified_requirement_coverage` is replaced through the
reviewed objective-projection v4 contract.

For a persisted M58 prefix, the denominator is the complete app-issued
opportunity set derived from the exact reviewed r6 requirements. The numerator
counts current `PASSED` objective results and current owned-native `ACCEPTED`
authorities. `FAILED` and `REJECTED` resolve their owned opportunities without
meeting them; `UNKNOWN` stays unresolved. Partial evidence remains nonnumeric
and bounded, a fully resolved non-empty set may become known, and an empty
reviewed set is `not_applicable`.

The corresponding typed receipt is sealed with the v4 verification engine,
algorithm, algorithm version, and no-rubric identity. This provenance is
validated on both save and hydration and cannot be replaced with the older v2
typed-objective label.

## Transaction, history, and reuse properties

- Evidence resolution is read-only and never issues an M58 opportunity set as
  a side effect of running models.
- Save revalidates the exact current M58 prefix in the same writer transaction
  that inserts the run graph and r8 sidecars.
- If an M58 append commits first, the stale run save rejects and the entire run
  graph rolls back.
- If the run save commits first, a later append waits, then succeeds; the old
  run remains valid against its historical bound revision.
- A historical `awaiting_evidence` marker remains readable after legitimate
  later opportunity issuance, including after restart.
- Exact revision-zero bindings are valid. Later revisions receive different
  request, binding, run, and publication identities.
- Exact same-revision replay may reuse the sealed run. Different verification
  revisions are conservatively incomparable in watch trajectories.
- Objective-result `observed_sequence` must strictly advance along its
  predecessor chain. M59 guards future writes, and repository hydration rejects
  malformed pre-M59 or trigger-bypassed history.

## Tamper and privacy properties

Hydration reissues and checks the keyed binding fingerprint, exact historical
M58 prefix, r6 authority, counts, twenty metric rows, typed provenance, and
publication seals. Missing rows, foreign identities, stale current heads,
ordinary-hash substitution, forged numerators, incomplete nineteen-row graphs,
recomputed seal fields, and mixed projection identities fail closed.

Rows are immutable and direct child deletion is rejected. Deletion through the
owning run removes the r8 binding/publication while leaving the independently
owned M58 evidence graph intact. Owning session/source privacy deletion
cascades the run sidecars and complete M58 graph. Local services remain
loopback-only.

## Readiness, operability, and UI contract

Readiness catalog `metric-evidence-readiness-v2-7` understands the r8 source
partitions and preserves the distinction between objective result receipts and
native acceptance. Operability catalog `metric-operability-v4` points to r8 but
does not promote any path merely because a durable binding exists.

The release inventory remains exactly:

- 16 shipped conditional evidence paths;
- 0 task-profile configuration gaps;
- 4 provider/extractor or release-composition gaps; and
- 0 model-authoritative measured metrics.

The HTTP and generated frontend contracts expose only the minimized,
content-free binding. Workspace operability, help, evidence-bound rendering,
and count bounds use the same r8/readiness-v2-7 identities. This checkpoint is
not a card-layout redesign; detailed UI card review remains separate.

## Cross-review defects repaired

Independent reviews caught these integration defects before the final gate:

1. historical `awaiting_evidence` runs initially required absence to remain
   current and became unreadable after legitimate later M58 issuance;
2. an r8 publication could initially omit the all-twenty typed receipt seal or
   carry non-v4 provenance for the verified-requirement typed row;
3. the intentional reviewed-r6 fallback with no composed verification reader
   was emitted as `unavailable` by the application but rejected by persistence;
4. frontend operability/help routing initially retained older catalog or
   projection identities;
5. frontend binding/count parsers did not consistently enforce the storage
   bounds and closed source shapes; and
6. the minimized HTTP DTO, generated client, and checked OpenAPI initially
   drifted during the parallel backend/frontend integration.

Each repair is required to remain covered by a focused synthetic regression.

## Verification status

- Focused application, migration, persistence, API, frontend, concurrency,
  restart, privacy, and tamper gates passed. The final combined backend slice
  passed 109 tests; the post-audit backend slice passed 85 tests; the root
  frontend slice passed 203 tests; and the post-audit frontend slice passed
  153 tests, including the four-case r8 readiness truth table.
- Full backend suite: **3,416 passed, 9 platform-skipped, 0 failed**, with the
  existing Starlette/httpx deprecation warning only.
- Full frontend suite: **115 files / 1,234 tests passed**. Checked TypeScript
  generation and the production build passed; Vite retains its advisory
  warning for the 523.15 kB main chunk (133.39 kB gzip).
- The exact OpenAPI artifact test, generated-client drift check, Python
  compilation, repository privacy scan, and diff validation passed. Diff
  validation emitted only non-semantic Windows LF-to-CRLF notices.
- The final service reload replaced only the verified repository process tree.
  One listener remained on `127.0.0.1:8765`; `/` and `/health` returned HTTP
  200.

Implementation is recorded in `5c8d49c` (M59/r8 application and persistence)
and `57b8086` (HTTP, OpenAPI, frontend, and live E2E contracts).
