# Local agent metric-evidence API

This boundary lets a local coding agent prepare a small, canonical JSON file
that Prompt Enhancer can validate and turn into an **unconfirmed** metric
proposal. It does not let the agent assign a score, declare task success, or
confirm its own evidence.

## Current coverage and identities

The historical `agent-metric-evidence-file-v1` contract is bound to projection
r4. The current append-only `agent-metric-evidence-file-v2` contract is bound to
projection r5 and additionally carries the exact sealed source-window
fingerprint. Both cover only the five collaboration lifecycle families:

- ambiguity resolution;
- clarification yield;
- exploration conversion;
- scope-change discipline;
- rework-candidate rate.

Neither version accepts prose, transcript excerpts, paths, model rationale,
numeric scores, or objective-verification claims. The reviewed task-profile
editor is a separate same-origin workflow for the three prompt denominators;
the five objective-receipt metrics still need their own reviewed evidence
adapters. This file format must not be presented as support for either boundary.

## Safe workflow

Before writing a file, the client may read the content-free all-twenty release
map from `GET /v1/metric-contracts/v2/operability-catalog`. This distinguishes a
currently supported evidence path from a task-profile or provider-adapter gap;
it does not disclose session data or authorize a measured value.

1. The authenticated loopback client reads
   `GET /v1/sessions/{session_id}/agent-metric-evidence/contract`. The response
   returns the contract matching the current sealed projection. The current v2
   response binds the exact sealed run, source-window fingerprint, all contract
   fingerprints, accepted closed enums, size limit, and expiry policy. A future
   projection identity fails with `agent_metric_evidence_definitions_out_of_date`
   instead of being misclassified as malformed input.
2. The agent writes canonical UTF-8 JSON using that exact contract. The body is
   at most 64 KiB, expires within 24 hours, contains no floating-point values,
   and uses sorted keys with no insignificant whitespace or duplicate keys.
3. The client sends the unchanged bytes to
   `POST /v1/sessions/{session_id}/agent-metric-evidence/preview` with media type
   `application/vnd.prompt-enhancer.agent-metric-evidence+json`. Previewing is
   read-only and returns the payload digest and exact source-window binding.
4. After displaying that preview, the client may import the same bytes through
   `POST /v1/sessions/{session_id}/agent-metric-evidence/import`, binding the
   preview digest, an idempotency key, and the literal import confirmation.
   Import creates only an inert proposal; raw bytes and producer claims are not
   persisted as evidence authority.
5. A person reviews the proposal in the same-origin dashboard. Confirming or
   rejecting it is a separate two-step action protected by the ephemeral
   browser session, CSRF token, exact decision-confirmation literal, and an
   origin- and body-bound one-shot capability issued after an owned native
   window displays fixed content-free confirmation copy. The decision endpoint
   refuses the general API token. Standard `serve`, attached windows, and
   unsupported hosts advertise the decision as unavailable and keep the
   proposal inert.
6. A new local analysis publishes any effect in a fresh sealed snapshot. The
   previous snapshot is never mutated.

Every response on these routes is private and non-cacheable. All identifiers
are installation-local pseudonyms, and stale run, window, revision, digest, or
contract bindings fail closed.

## Reviewed task-profile API

The profile denominator workflow is intentionally not an agent-evidence file.
An authenticated client may read
`GET /v1/sessions/{session_id}/declared-task-profile`, but saving a revision at
the same path requires the ephemeral same-origin browser session, CSRF and
Origin checks, an idempotency key, the exact predecessor revision, the literal
`save_reviewed_declared_task_profile` confirmation, and the same owned-window
native capability. The closed payload
can contain only sorted constraint kinds, an expected outcome count from 1 to
100, and sorted deliverable slots. `null` means unconfigured/unknown; empty
configured collections are invalid.

The service persists no request text. A new analysis resolves the latest
immutable profile before reading the provider window, includes its revision and
fingerprint in request identity, and seals that binding beside the r5
publication. Acceptance testability counts distinct checkable clauses owned by
the canonical active request, capped by the reviewed expected-outcome count;
superseded text and repeated cues cannot inflate the numerator. Changing the
profile therefore creates a different run even if the final numeric states
happen to match.

## Threat boundary

The API-token/browser-session/native-capability split prevents the same HTTP
credential from both proposing and admitting evidence. The native dialog copy
contains no identifiers, paths, request body, or provider content. It is not
proof of physical human presence against malware that can control the local
desktop or automate native dialogs. A
future commercial remote API must add account entitlements, scoped API clients,
revocation, audit, rate limits, and a reviewed user-presence mechanism; it must
not weaken this local confirmation boundary.
