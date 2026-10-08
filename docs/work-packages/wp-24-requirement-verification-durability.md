# WP-24: Requirement-verification durability and local API

Status: **Checkpoint 7A implemented and validated; live metric activation
deliberately deferred to Checkpoint 7B**

## Outcome

This checkpoint turns the pure WP-23 authority types into a restart-safe,
append-only local workflow. It does not change the live objective projection,
readiness, operability, or the current 16/0/4 release partition.

The durable authority path is:

1. resolve the latest sealed local analysis window without transcript or
   ephemeral review-context state;
2. load the exact owned-native-confirmed r6 requirement snapshot for that
   window;
3. deterministically issue and seal one content-free opportunity for every
   active requirement;
4. append either a pre-issued keyed objective result or a separately typed
   owned-native acceptance;
5. expose any exact dense revision as a content-free evidence snapshot; and
6. replay the same idempotent command exactly, including after a source window
   has aged, while rejecting changed commands and new stale-window writes.

Assistant completion claims, requirement-action completion, model judgments,
provider prose, and client-minted pass/fail claims remain outside the authority
graph.

## M58 storage boundary

Migration 58 appends six strict tables after byte-frozen migrations 1-57:

- `requirement_verification_opportunity_sets`;
- `requirement_verification_opportunities`;
- `requirement_verification_opportunity_set_seals`;
- `requirement_verification_authority_records`;
- `requirement_verification_result_receipt_refs`; and
- `requirement_verification_authority_record_seals`.

The schema stores only installation-keyed identifiers, r6 coordinates, closed
enums, bounded counts, versions, fingerprints, dense revisions, and UTC server
times. It has no prompt, transcript, path, output, provider payload, assistant
claim, or free-form proof column.

Writes use `BEGIN IMMEDIATE`, an exact predecessor per opportunity, a dense
revision per opportunity set, and a unique session-scoped idempotency digest.
The repository reissues and validates all keyed identities on every read and
write. Missing seals, gaps, foreign ownership, mixed authority kinds, malformed
versions, and direct-SQL tampering fail closed rather than being skipped.

Rows are immutable. Direct child deletion is rejected, while deletion through
the owning session or source-run privacy lifecycle cascades the complete graph.

## Local HTTP surface

The content-free endpoints are:

- `POST /v1/sessions/{session_id}/requirement-verification-evidence/opportunity-sets/current`;
- `GET /v1/sessions/{session_id}/requirement-verification-evidence/opportunity-sets/{opportunity_set_fingerprint}`;
- `POST /v1/sessions/{session_id}/requirement-verification-evidence/objective-results`;
- `POST /v1/sessions/{session_id}/requirement-verification-evidence/acceptances`.

Issuance, reads, and pre-issued objective-result appends use local
authentication. Acceptance is a distinct owned-native action: API-token and
Bearer credentials are rejected, and the route requires an ephemeral browser
cookie, exact same-origin header, CSRF proof, a one-shot path/body-bound native
presence capability, and the closed confirmation literal.

All route responses are private/no-store. OpenAPI documents the actual browser
requirements and sanitized 401/403/404/409/422/503 response shapes. The
generated TypeScript client is byte-checked against that schema.

## Synthetic verification

Focused and end-to-end tests cover:

- owned-native r6 review through public HTTP issuance and append;
- zero, incomplete, unknown, passed, failed, accepted, and rejected evidence;
- moving-clock replay, idempotency conflicts, predecessor conflicts, and two-
  connection writer races;
- dense historical snapshots and restart rehydration;
- stale r6 successors, foreign sessions/sets/results, authority-kind switching,
  malformed and model-authored inputs, and direct-SQL tampering;
- schema rollback, M57 checksum freeze, strict/content-free M58 shape, source-
  run and session privacy cascades;
- no raw canaries in API bodies, errors, model representations, the SQLite
  database, or its exact WAL/SHM siblings; and
- unchanged readiness and operability truth.

The final locked repository gates passed 3,366 backend tests with nine
platform skips, all 1,219 frontend tests, TypeScript and production builds,
OpenAPI drift validation, Python compilation, the repository privacy scanner,
and diff validation. The one retained backend warning is the existing
Starlette/httpx deprecation notice.

## Deferred Checkpoint 7B

M58 records durable evidence but does not prove which evidence revision was
sealed into a particular model-ensemble run. Activating the pure v4 objective
projection without that binding would make restart and run reuse unverifiable.

Checkpoint 7B must therefore append a new migration and atomically seal a
content-free run binding containing the exact opportunity-set fingerprint,
evidence-set fingerprint, through-revision, r6 identities, and all relevant
schema/policy/issuer/projection versions. Only after restart, stale-head,
tamper, rollback, and concurrency tests pass may the live pipeline call the v4
objective projector. It must not rewrite r7 history or promote readiness or
operability by implication.
